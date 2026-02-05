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
    # "+ 패치 2개", "패치 2매 증정", "알콜솜 증정" 등
    gift_patterns = [
        r"\+\s*패치\s*\d+\s*(개|매|장)?",      # + 패치 2개
        r"패치\s*\d+\s*(개|매|장)?\s*(증정|사은품|포함)?",  # 패치 2개 증정
        r"\+\s*알콜\s*(솜|스왑|스웹)?\s*\d+\s*(개|매|장)?",  # + 알콜솜 2매
        r"알콜\s*(솜|스왑|스웹)?\s*\d+\s*(개|매|장)?\s*(증정|사은품|포함)?",
        r"\+\s*방수\s*(필름|패치)?\s*\d+\s*(개|매|장)?",
        r"방수\s*(필름|패치)?\s*\d+\s*(개|매|장)?\s*(증정|사은품|포함)?",
        r"아메리카노\s*\d+\s*(개|잔)?",
        r"커피\s*\d+\s*(개|잔)?",
        r"멤버십\s*\d+\s*일",
        r"\d+\s*일\s*(체험|멤버십)",
        r"유효기간\s*\d+\s*일",
        r"사은품[^+]*",                        # "사은품 ~" 전체
        r"증정[^+]*",                          # "증정 ~" 전체
    ]
    
    for pattern in gift_patterns:
        clean_title = re.sub(pattern, " ", clean_title, flags=re.IGNORECASE)
    
    # 2. 센서/측정기 관련 수량 우선 추출
    # "측정기 2개", "센서 3개입", "리브레2 x3" 등
    sensor_qty_patterns = [
        r"(측정기|센서|리브레\s*2?)\s*(\d+)\s*(개|개입|세트|팩|박스)",  # 측정기 2개
        r"(\d+)\s*(개|개입|세트|팩|박스)\s*(측정기|센서)",              # 2개 측정기
        r"(측정기|센서|리브레)\s*[xX*]\s*(\d+)",                       # 센서 x3
    ]
    
    sensor_qty = None
    for pattern in sensor_qty_patterns:
        match = re.search(pattern, clean_title, re.IGNORECASE)
        if match:
            # 숫자가 있는 그룹 찾기
            for group in match.groups():
                if group and group.isdigit():
                    sensor_qty = int(group)
                    break
            if sensor_qty:
                break
    
    # 3. 센서 수량을 못 찾으면 일반 패턴으로 추출
    if sensor_qty is None:
        qty_candidates = []
        
        # 일반 수량 패턴 (공백 또는 x 뒤의 숫자 + 단위)
        matches = re.findall(r"[\s](\d+)\s*(개|개입|세트|팩|박스|ea|set)", clean_title, re.IGNORECASE)
        for m in matches:
            qty_candidates.append(int(m[0]))
        
        # x3, X5, *2 패턴
        matches_mul = re.findall(r"[xX*]\s*(\d+)", clean_title)
        for m in matches_mul:
            qty_candidates.append(int(m))
        
        # 첫 번째로 찾은 숫자 사용 (마지막이 아닌 첫 번째 - 보통 메인 상품이 앞에 옴)
        sensor_qty = qty_candidates[0] if qty_candidates else 1
    
    # 4. 단가 계산 및 검증
    MIN_PRICE, MAX_PRICE = 65000, 160000
    calc_unit_price = total_price // sensor_qty if sensor_qty > 0 else total_price
    
    if MIN_PRICE <= calc_unit_price <= MAX_PRICE:
        return sensor_qty, calc_unit_price, "텍스트분석"
    else:
        # 가격 역산으로 수량 추정
        estimated_qty = round(total_price / 90000) or 1
        recalc_price = total_price // estimated_qty if estimated_qty > 0 else total_price
        
        if MIN_PRICE <= recalc_price <= MAX_PRICE:
            return estimated_qty, recalc_price, "가격역산(보정)"
        else:
            # 그래도 안 맞으면 원래 계산값 반환
            return sensor_qty, calc_unit_price, "확인필요"


def is_excluded_product(title):
    """
    프리스타일 리브레 센서 본품만 포함, 액세서리는 제외
    
    핵심 로직: "센서" 또는 "측정기"가 있어야 포함
    """
    title_lower = title.lower()
    
    # ========== 1. 필수 키워드 체크 ==========
    # "센서" 또는 "측정기"가 없으면 무조건 제외
    sensor_keywords = ["센서", "측정기", "sensor"]
    has_sensor = any(kw in title_lower for kw in sensor_keywords)
    
    if not has_sensor:
        print(f"  ⛔ 제외 (센서/측정기 없음): {title[:50]}...")
        return True  # 제외
    
    # ========== 2. 액세서리 패턴 제외 ==========
    # "센서"가 있어도 액세서리인 경우
    
    # 2-1. "숫자+팩/매 + 커버/패치" 패턴 (액세서리 대량팩)
    accessory_quantity_patterns = [
        r"\d+\s*팩\s*(커버|패치|필름)",      # 25팩 커버
        r"\d+\s*매\s*(커버|패치|필름)",      # 20매 패치
        r"\d+\s*pack",                       # 40 Pack
        r"\d+\s*pcs",                        # 25pcs
    ]
    
    for pattern in accessory_quantity_patterns:
        if re.search(pattern, title_lower):
            print(f"  ⛔ 제외 (액세서리 대량팩): {title[:50]}...")
            return True
    
    # 2-2. 액세서리 키워드 (센서가 있어도 제외)
    accessory_keywords = [
        # 케이스/커버류
        "홀스터", "holster", "케이스", "case", "파우치", "pouch",
        "커버", "cover", "클립", "clip",
        # 보호필름/패치류  
        "보호기", "protector", "필름", "film", "스크린", "screen",
        "패치", "patch", "스티커", "sticker", "테이프", "tape",
        # 기타 액세서리
        "랜야드", "lanyard", "스트랩", "strap", "밴드", "band",
        "케이블", "cable", "충전", "charger", "charging",
        "거치대", "holder", "stand",
    ]
    
    for keyword in accessory_keywords:
        if keyword in title_lower:
            print(f"  ⛔ 제외 (액세서리 키워드 '{keyword}'): {title[:50]}...")
            return True
    
    # ========== 3. 통과 ==========
    return False


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
                
                # 카테고리 정보
                category1 = item.get("category1", "")
                category2 = item.get("category2", "")
                category3 = item.get("category3", "")
                category4 = item.get("category4", "")
                
                # 카테고리 필터: "혈당계" 또는 "당뇨관리용품"이 있어야 함
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
    
    # 디버깅: 환경 변수 확인
    print(f"🔍 환경 변수 확인:")
    print(f"   MYSQLHOST: {os.getenv('MYSQLHOST')}")
    print(f"   MYSQLUSER: {os.getenv('MYSQLUSER')}")
    print(f"   MYSQLDATABASE: {os.getenv('MYSQLDATABASE')}")
    print(f"   DB_HOST: {config.DB_HOST}")
    
    # Railway 환경에서는 자동으로 MySQL 환경 변수 사용
    if os.getenv("MYSQLHOST"):
        db_host = os.getenv("MYSQLHOST")
        db_user = os.getenv("MYSQLUSER")
        db_password = os.getenv("MYSQLPASSWORD")
        db_name = os.getenv("MYSQLDATABASE")
        db_port = int(os.getenv("MYSQLPORT", 3306))
        print(f"✅ Railway MySQL 환경 변수 사용: {db_host}:{db_port}")
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
