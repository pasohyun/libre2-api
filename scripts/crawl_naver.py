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
    """
    상품명에서 센서 수량과 단가를 분석

    핵심: 센서/측정기 수량만 추출, 사은품(패치, 알콜솜 등)은 무시
    """
    clean_title = title

    # 1. 사은품/증정품 관련 구문 전체 제거
    gift_patterns = [
        r"\+\s*패치\s*\d+\s*(개|매|장)?",
        r"패치\s*\d+\s*(개|매|장)?\s*(증정|사은품|포함)?",
        r"\+\s*알콜\s*(솜|스왑|스웹)?\s*\d+\s*(개|매|장)?",
        r"알콜\s*(솜|스왑|스웹)?\s*\d+\s*(개|매|장)?\s*(증정|사은품|포함)?",
        r"\+\s*방수\s*(필름|패치)?\s*\d+\s*(개|매|장)?",
        r"방수\s*(필름|패치)?\s*\d+\s*(개|매|장)?\s*(증정|사은품|포함)?",
        r"아메리카노\s*\d+\s*(개|잔)?",
        r"커피\s*\d+\s*(개|잔)?",
        r"멤버십\s*\d+\s*일",
        r"\d+\s*일\s*(체험|멤버십)",
        r"유효기간\s*\d+\s*일",
        r"사은품[^+]*",
        r"증정[^+]*",
    ]

    for pattern in gift_patterns:
        clean_title = re.sub(pattern, " ", clean_title, flags=re.IGNORECASE)

    # 2. 센서/측정기 관련 수량 우선 추출
    sensor_qty_patterns = [
        r"(측정기|센서|리브레\s*2?)\s*(\d+)\s*(개|개입|세트|팩|박스)",
        r"(\d+)\s*(개|개입|세트|팩|박스)\s*(측정기|센서)",
        r"(측정기|센서|리브레)\s*[xX*]\s*(\d+)",
    ]

    sensor_qty = None
    qty_from_text = False

    for pattern in sensor_qty_patterns:
        match = re.search(pattern, clean_title, re.IGNORECASE)
        if match:
            for group in match.groups():
                if group and group.isdigit():
                    sensor_qty = int(group)
                    break
            if sensor_qty:
                qty_from_text = True
                break

    # 3. 센서 수량을 못 찾으면 일반 패턴으로 추출
    if sensor_qty is None:
        qty_candidates = []

        matches = re.findall(r"[\s](\d+)\s*(개|개입|세트|팩|박스|ea|set)", clean_title, re.IGNORECASE)
        for m in matches:
            qty_candidates.append(int(m[0]))

        matches_mul = re.findall(r"[xX*]\s*(\d+)", clean_title)
        for m in matches_mul:
            qty_candidates.append(int(m))

        if qty_candidates:
            sensor_qty = qty_candidates[0]
            qty_from_text = True
        else:
            sensor_qty = 1
            qty_from_text = False

    # 4. 단가 계산 및 검증
    MIN_PRICE, MAX_PRICE = 65000, 180000
    calc_unit_price = total_price // sensor_qty if sensor_qty > 0 else total_price

    if MIN_PRICE <= calc_unit_price <= MAX_PRICE:
        return sensor_qty, calc_unit_price, "텍스트분석"

    if qty_from_text:
        return sensor_qty, calc_unit_price, "텍스트분석(범위초과)"

    estimated_qty = round(total_price / 90000) or 1
    recalc_price = total_price // estimated_qty if estimated_qty > 0 else total_price

    if MIN_PRICE <= recalc_price <= MAX_PRICE:
        return estimated_qty, recalc_price, "가격역산(보정)"
    else:
        return sensor_qty, calc_unit_price, "확인필요"


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

                category1 = item.get("category1", "")
                category2 = item.get("category2", "")
                category3 = item.get("category3", "")
                category4 = item.get("category4", "")

                valid_categories = ["혈당계", "혈당측정기", "당뇨관리용품", "당뇨"]
                all_categories = f"{category1} {category2} {category3} {category4}".lower()

                if not any(cat in all_categories for cat in valid_categories):
                    print(f"  ⛔ 제외 (카테고리: {category2}/{category3}): {title[:40]}...")
                    continue

                qty, unit_price, method = analyze_product(title, total_price)

                if unit_price < 65000:
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
                    "channel": "naver",
                    "market": "스마트스토어",
                })

            kept_now = len(all_results)
            print(f"page start={start} fetched={len(items)} kept={kept_now - kept_before} kept_total={kept_now}")

            start += display
            time.sleep(0.2)

        except Exception as e:
            print("API error:", e)
            break

    return all_results


# ✅ (1) calc_valid 함수 추가
def _calc_valid(calc_method: str) -> int:
    cm = (calc_method or "").strip()
    if "확인" in cm or "범위초과" in cm:
        return 0
    return 1


# ✅ (2) save_to_db 시그니처 변경 + INSERT 컬럼 추가
def save_to_db(rows, *, snapshot_id: str, snapshot_at: datetime):
    import os

    print(f"🔍 환경 변수 확인:")
    print(f"   MYSQLHOST: {os.getenv('MYSQLHOST')}")
    print(f"   MYSQLUSER: {os.getenv('MYSQLUSER')}")
    print(f"   MYSQLDATABASE: {os.getenv('MYSQLDATABASE')}")
    print(f"   DB_HOST: {config.DB_HOST}")

    if os.getenv("MYSQLHOST"):
        db_host = os.getenv("MYSQLHOST")
        db_user = os.getenv("MYSQLUSER")
        db_password = os.getenv("MYSQLPASSWORD")
        db_name = os.getenv("MYSQLDATABASE")
        db_port = int(os.getenv("MYSQLPORT", 3306))
        print(f"✅ Railway MySQL 환경 변수 사용: {db_host}:{db_port}")
    elif config.DB_HOST:
        db_host = config.DB_HOST
        db_user = config.DB_USER
        db_password = config.DB_PASSWORD
        db_name = config.DB_NAME
        db_port = config.DB_PORT
    else:
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
      mall_name, calc_method, link, image_url, card_image_path,
      channel, market,
      snapshot_id, snapshot_at, calc_valid,
      created_at
    ) VALUES (
      %s,%s,%s,%s,%s,
      %s,%s,%s,%s,%s,
      %s,%s,
      %s,%s,%s,
      NOW()
    )
    """

    data = []
    for r in rows:
        data.append(
            (
                r["keyword"],
                r["product_name"],
                r["unit_price"],
                r["quantity"],
                r["total_price"],
                r["mall_name"],
                r["calc_method"],
                r["link"],
                r["image_url"],
                r["card_image_path"],
                r.get("channel", "naver"),
                r.get("market", "스마트스토어"),
                snapshot_id,
                snapshot_at.strftime("%Y-%m-%d %H:%M:%S"),
                _calc_valid(r.get("calc_method")),
            )
        )

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

    # ✅ (3) run_crawling에서 snapshot_id/snapshot_at 생성 후 save_to_db에 전달
    snapshot_at = datetime.now().replace(minute=0, second=0, microsecond=0)
    snapshot_id = snapshot_at.strftime("%Y%m%d%H")

    inserted = save_to_db(rows, snapshot_id=snapshot_id, snapshot_at=snapshot_at)
    print(f"DB inserted: {inserted}")
    print(f"END: {datetime.now().isoformat(timespec='seconds')}")


if __name__ == "__main__":
    run_crawling()
