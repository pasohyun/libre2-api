import urllib.request
import urllib.parse
import json
import re
import time
from datetime import datetime

import mysql.connector
import pandas as pd

import config

CLIENT_ID = config.NAVER_CLIENT_ID
CLIENT_SECRET = config.NAVER_CLIENT_SECRET


def analyze_product(title, total_price):
    clean_title = title

    black_list = [
        r"아메리카노\s*\d+개", r"커피\s*\d+잔", r"커피\s*\d+개",
        r"패치\s*\d+매", r"패치\s*\d+개", r"알콜솜\s*\d+매",
        r"방수필름\s*\d+매", r"멤버십\s*\d+일", r"유효기간\s*\d+일",
        r"\d+일\s*체험", r"\d+일\s*멤버십"
    ]
    for pattern in black_list:
        clean_title = re.sub(pattern, " ", clean_title)

    qty_candidates = []
    matches = re.findall(r"[\sxX](\d+)\s*(개|세트|팩|박스|ea|set)", clean_title, re.IGNORECASE)
    for m in matches:
        qty_candidates.append(int(m[0]))
    matches_mul = re.findall(r"[xX*]\s*(\d+)", clean_title)
    for m in matches_mul:
        qty_candidates.append(int(m))

    extracted_qty = qty_candidates[-1] if qty_candidates else 1

    MIN_PRICE, MAX_PRICE = 65000, 130000
    calc_unit_price = total_price // extracted_qty

    if MIN_PRICE <= calc_unit_price <= MAX_PRICE:
        return extracted_qty, calc_unit_price, "텍스트분석"
    else:
        estimated_qty = round(total_price / 90000) or 1
        recalc_price = total_price // estimated_qty
        if MIN_PRICE <= recalc_price <= MAX_PRICE:
            return estimated_qty, recalc_price, "가격역산(보정)"
        else:
            return extracted_qty, calc_unit_price, "확인필요"


def get_naver_data_all(query):
    enc = urllib.parse.quote(query)
    all_results = []
    start = 1
    display = 100

    while True:
        if start > 1000:
            break

        url = f"https://openapi.naver.com/v1/search/shop.json?query={enc}&display={display}&start={start}&sort=sim"
        request = urllib.request.Request(url)
        request.add_header("X-Naver-Client-Id", CLIENT_ID)
        request.add_header("X-Naver-Client-Secret", CLIENT_SECRET)

        try:
            response = urllib.request.urlopen(request)
            if response.getcode() != 200:
                print("API status:", response.getcode())
                break

            data = json.loads(response.read().decode("utf-8"))
            items = data.get("items", [])
            if not items:
                break

            kept_before = len(all_results)

            for item in items:
                title = item.get("title", "").replace("<b>", "").replace("</b>", "")
                total_price = int(item.get("lprice", 0) or 0)
                image_url = item.get("image", "")
                mall = item.get("mallName", "")
                link = item.get("link", "")

                qty, unit_price, method = analyze_product(title, total_price)

                if unit_price < 50000:
                    continue

                all_results.append({
                    "keyword": query,
                    "product_name": title,
                    "unit_price": unit_price,
                    "quantity": qty,
                    "total_price": total_price,
                    "mall_name": mall,
                    "calc_method": method,
                    "link": link,
                    "image_url": image_url,
                    "card_image_path": None,
                    "channel": "naver",  # 네이버 크롤링이므로 "naver"
                    "market": "스마트스토어",  # 네이버는 스마트스토어
                })

            kept_now = len(all_results)
            print(f"page start={start} fetched={len(items)} kept={kept_now - kept_before} kept_total={kept_now}")

            start += display
            time.sleep(0.2)

        except Exception as e:
            print("API error:", e)
            break

    return all_results


def save_to_db(rows):
    import os
    
    # Railway 환경에서는 자동으로 MySQL 환경 변수 사용
    if os.getenv("MYSQLHOST"):
        db_host = os.getenv("MYSQLHOST")
        db_user = os.getenv("MYSQLUSER")
        db_password = os.getenv("MYSQLPASSWORD")
        db_name = os.getenv("MYSQLDATABASE")
        db_port = int(os.getenv("MYSQLPORT", 3306))
    elif config.DB_HOST:
        # 일반 환경 변수 사용
        db_host = config.DB_HOST
        db_user = config.DB_USER
        db_password = config.DB_PASSWORD
        db_name = config.DB_NAME
        db_port = config.DB_PORT
    else:
        # Railway 환경인데 MySQL 환경 변수가 없음
        print("❌ DB 연결 정보가 없습니다.")
        print("   Railway 환경에서는 Cron Job 서비스의 Variables에 다음을 추가하세요:")
        print("   MYSQLHOST = ${{ MySQL.MYSQLHOST }}")
        print("   MYSQLUSER = ${{ MySQL.MYSQLUSER }}")
        print("   MYSQLPASSWORD = ${{ MySQL.MYSQLPASSWORD }}")
        print("   MYSQLDATABASE = ${{ MySQL.MYSQLDATABASE }}")
        print("   MYSQLPORT = ${{ MySQL.MYSQLPORT }}")
        return 0

    conn = mysql.connector.connect(
        host=db_host,
        port=db_port,
        user=db_user,
        password=db_password,
        database=db_name,
        charset="utf8mb4",
    )
    cur = conn.cursor()

    sql = f"""
    INSERT INTO {config.DB_TABLE} (
      keyword, product_name, unit_price, quantity, total_price,
      mall_name, calc_method, link, image_url, card_image_path, channel, market, created_at
    ) VALUES (
      %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW()
    )
    """

    data = []
    for r in rows:
        data.append((
            r["keyword"], r["product_name"], r["unit_price"], r["quantity"], r["total_price"],
            r["mall_name"], r["calc_method"], r["link"], r["image_url"], r["card_image_path"],
            r.get("channel", "naver"), r.get("market", "스마트스토어")
        ))

    cur.executemany(sql, data)
    conn.commit()
    inserted = cur.rowcount

    cur.close()
    conn.close()
    return inserted


def run_crawling():
    print(f"START: {datetime.now().isoformat(timespec='seconds')}")
    keyword = config.SEARCH_KEYWORD

    rows = get_naver_data_all(keyword)
    print(f"Fetched: {len(rows)} rows")

    inserted = save_to_db(rows)
    print(f"DB inserted: {inserted}")
    print(f"END: {datetime.now().isoformat(timespec='seconds')}")


if __name__ == "__main__":
    run_crawling()
