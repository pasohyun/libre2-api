import os
import urllib.request
import urllib.parse
import json
import re
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import mysql.connector
import pandas as pd

import config

try:
    from api.services.card_renderer import render_card_png
    _card_renderer_import_error = None
except Exception as e:
    render_card_png = None
    _card_renderer_import_error = e

try:
    from api.services.s3_storage import is_s3_enabled, upload_bytes
    _s3_storage_import_error = None
except Exception as e:
    is_s3_enabled = None
    upload_bytes = None
    _s3_storage_import_error = e

CLIENT_ID = config.NAVER_CLIENT_ID
CLIENT_SECRET = config.NAVER_CLIENT_SECRET
KST = ZoneInfo("Asia/Seoul")
NAVER_API_TIMEOUT_SEC = int(os.getenv("NAVER_API_TIMEOUT_SEC", "20"))
NAVER_API_MAX_RETRIES = int(os.getenv("NAVER_API_MAX_RETRIES", "3"))
VERBOSE_EXCLUDE_LOG = os.getenv("VERBOSE_EXCLUDE_LOG", "false").lower() == "true"


def _log(message: str):
    # Cron 환경에서 출력 버퍼링으로 로그가 늦게 보이는 문제를 줄인다.
    print(message, flush=True)


def _dedupe_rows(rows):
    """
    동일 실행(run) 내 중복 상품 제거.
    링크가 있으면 링크 기준, 없으면 핵심 필드 조합 기준으로 dedupe.
    """
    if not rows:
        return []

    seen = set()
    deduped = []
    for r in rows:
        link = (r.get("link") or "").strip()
        if link:
            key = ("link", link)
        else:
            key = (
                "fallback",
                (r.get("mall_name") or "").strip(),
                (r.get("product_name") or "").strip(),
                int(r.get("unit_price") or 0),
                int(r.get("quantity") or 0),
                int(r.get("total_price") or 0),
            )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


def _upload_product_images_to_s3(rows, *, snapshot_id: str):
    """
    최신 스냅샷 중 일부 상품 이미지를 S3에 업로드하고 card_image_path에 URL 저장.
    비용/시간 제어를 위해 업로드 건수는 S3_UPLOAD_MAX_PER_RUN으로 제한.
    """
    if not rows:
        return 0

    if not config.ENABLE_CARD_RENDER:
        _log("S3 card upload skipped: ENABLE_CARD_RENDER is false")
        return 0

    if _card_renderer_import_error is not None or render_card_png is None:
        _log(f"S3 card upload skipped: card renderer import failed: {_card_renderer_import_error}")
        return 0

    if _s3_storage_import_error is not None or is_s3_enabled is None or upload_bytes is None:
        _log(f"S3 card upload skipped: s3 storage import failed: {_s3_storage_import_error}")
        return 0

    if not is_s3_enabled():
        return 0

    uploaded = 0
    consecutive_failures = 0
    threshold = config.TARGET_PRICE
    candidates = [r for r in rows if int(r.get("unit_price") or 0) <= threshold]
    if not candidates:
        _log(f"S3 card upload skipped: no products at or below target price ({threshold:,}원)")
        return 0
    candidates = sorted(candidates, key=lambda x: x.get("unit_price") or 0)
    _log(
        f"S3 card upload candidates: {len(candidates)} / {len(rows)} "
        f"(<= {threshold:,}원)"
    )
    max_upload = config.S3_UPLOAD_MAX_PER_RUN
    if max_upload <= 0:
        max_upload = len(candidates)

    for idx, row in enumerate(candidates, start=1):
        if uploaded >= max_upload:
            break

        try:
            captured_at = datetime.now(KST)
            local_png_path = render_card_png(
                product=row,
                out_dir=os.path.join("product_cards", snapshot_id),
                captured_at=captured_at,
            )
            with open(local_png_path, "rb") as f:
                content = f.read()
            content_type = "image/png"
            ext = ".png"

            key = (
                f"{config.S3_PREFIX.strip('/')}/products/{snapshot_id}/"
                f"{uploaded + 1:04d}_{idx:04d}{ext}"
            )
            s3_url = upload_bytes(content=content, object_key=key, content_type=content_type)
            row["card_image_path"] = s3_url
            uploaded += 1
            consecutive_failures = 0
        except Exception as e:
            consecutive_failures += 1
            _log(f"⚠️ 카드 렌더/S3 업로드 실패 (row #{idx}): {e}")
            # 카드 렌더가 불가능한 런타임이면 연속 실패하므로 불필요한 반복을 중단
            error_text = str(e)
            if "libglib-2.0.so.0" in error_text or "BrowserType.launch" in error_text:
                _log("Playwright runtime dependency missing. Stop card upload loop.")
                break
            if (
                "can't start new thread" in error_text
                or "Resource temporarily unavailable" in error_text
                or "Cannot allocate memory" in error_text
                or "pthread_create failed" in error_text
            ):
                _log("Runtime resource limit reached during card rendering. Stop card upload loop.")
                break
            if consecutive_failures >= 5:
                _log("Too many consecutive card upload failures. Stop card upload loop.")
                break

    return uploaded


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
            response = None
            for attempt in range(1, NAVER_API_MAX_RETRIES + 1):
                try:
                    response = urllib.request.urlopen(request, timeout=NAVER_API_TIMEOUT_SEC)
                    break
                except Exception as api_req_error:
                    _log(
                        f"API request failed (attempt {attempt}/{NAVER_API_MAX_RETRIES}): "
                        f"{api_req_error}"
                    )
                    if attempt < NAVER_API_MAX_RETRIES:
                        time.sleep(attempt)
            if response is None:
                _log("API request failed after retries; stop this crawl run.")
                break
            if response.getcode() != 200:
                _log(f"API status: {response.getcode()}")
                break

            data = json.loads(response.read().decode("utf-8"))
            items = data.get("items", [])
            if not items:
                break

            kept_before = len(all_results)
            excluded_by_category = 0
            excluded_by_accessory = 0

            for item in items:
                title = item.get("title", "").replace("<b>", "").replace("</b>", "")
                total_price = int(item.get("lprice", 0) or 0)
                image_url = item.get("image", "")
                mall = item.get("mallName", "")
                if (mall or "").strip() == "네이버":
                    mall = "최저가비교"
                link = item.get("link", "")

                category1 = item.get("category1", "")
                category2 = item.get("category2", "")
                category3 = item.get("category3", "")
                category4 = item.get("category4", "")

                valid_categories = ["혈당계", "혈당측정기", "당뇨관리용품", "당뇨"]
                all_categories = f"{category1} {category2} {category3} {category4}".lower()

                if not any(cat in all_categories for cat in valid_categories):
                    excluded_by_category += 1
                    if VERBOSE_EXCLUDE_LOG:
                        _log(f"  ⛔ 제외 (카테고리: {category2}/{category3}): {title[:40]}...")
                    continue

                # 액세서리/부속품 키워드 제외 필터
                accessory_keywords = [
                    "스크린 프로텍터", "화면 보호", "보호필름", "보호 필름",
                    "케이스", "커버", "파우치", "홀스터", "랜야드",
                    "충전 케이블", "충전케이블", "USB 케이블",
                    "스킨그립", "스킨 그립", "오버패치",
                    "클립", "카라비너", "벨트 클립",
                ]
                title_lower = title.lower()
                if any(kw.lower() in title_lower for kw in accessory_keywords):
                    # 단, "센서"가 메인 상품명에 포함된 경우는 제외하지 않음
                    if not re.search(r"센서\s*\d+\s*(개|팩|세트|박스)", title):
                        excluded_by_accessory += 1
                        if VERBOSE_EXCLUDE_LOG:
                            _log(f"  ⛔ 제외 (액세서리): {title[:50]}...")
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
            _log(
                "page start="
                f"{start} fetched={len(items)} kept={kept_now - kept_before} "
                f"excluded_category={excluded_by_category} "
                f"excluded_accessory={excluded_by_accessory} "
                f"kept_total={kept_now}"
            )

            start += display
            time.sleep(0.2)

        except Exception as e:
            _log(f"API error: {e}")
            break

    return all_results


# ✅ (1) calc_valid 함수 추가
def _calc_valid(calc_method: str) -> int:
    cm = (calc_method or "").strip()
    if "확인" in cm or "범위초과" in cm:
        return 0
    return 1


def _norm_text(value) -> str:
    return (value or "").strip()


def _row_state_signature(row: dict):
    return (
        int(row.get("unit_price") or 0),
        int(row.get("quantity") or 0),
        int(row.get("total_price") or 0),
        _norm_text(row.get("calc_method")),
        _norm_text(row.get("image_url")),
        _norm_text(row.get("card_image_path")),
    )


def _db_state_signature(db_row):
    return (
        int(db_row[0] or 0),
        int(db_row[1] or 0),
        int(db_row[2] or 0),
        _norm_text(db_row[3]),
        _norm_text(db_row[4]),
        _norm_text(db_row[5]),
    )


def _is_same_as_latest_row(cur, row: dict) -> bool:
    link = _norm_text(row.get("link"))
    if link:
        cur.execute(
            f"""
            SELECT unit_price, quantity, total_price, calc_method, image_url, card_image_path
            FROM {config.DB_TABLE}
            WHERE link = %s
            ORDER BY COALESCE(snapshot_at, created_at) DESC, id DESC
            LIMIT 1
            """,
            (link,),
        )
    else:
        cur.execute(
            f"""
            SELECT unit_price, quantity, total_price, calc_method, image_url, card_image_path
            FROM {config.DB_TABLE}
            WHERE channel = %s
              AND market = %s
              AND mall_name = %s
              AND product_name = %s
            ORDER BY COALESCE(snapshot_at, created_at) DESC, id DESC
            LIMIT 1
            """,
            (
                _norm_text(row.get("channel")) or "naver",
                _norm_text(row.get("market")) or "스마트스토어",
                _norm_text(row.get("mall_name")),
                _norm_text(row.get("product_name")),
            ),
        )

    latest = cur.fetchone()
    if latest is None:
        return False
    return _db_state_signature(latest) == _row_state_signature(row)


# ✅ (2) save_to_db 시그니처 변경 + INSERT 컬럼 추가
def save_to_db(rows, *, snapshot_id: str, snapshot_at: datetime):
    import os

    _log(f"🔍 환경 변수 확인:")
    _log(f"   MYSQLHOST: {os.getenv('MYSQLHOST')}")
    _log(f"   MYSQLUSER: {os.getenv('MYSQLUSER')}")
    _log(f"   MYSQLDATABASE: {os.getenv('MYSQLDATABASE')}")
    _log(f"   DB_HOST: {config.DB_HOST}")

    if os.getenv("MYSQLHOST"):
        db_host = os.getenv("MYSQLHOST")
        db_user = os.getenv("MYSQLUSER")
        db_password = os.getenv("MYSQLPASSWORD")
        db_name = os.getenv("MYSQLDATABASE")
        db_port = int(os.getenv("MYSQLPORT", 3306))
        _log(f"✅ Railway MySQL 환경 변수 사용: {db_host}:{db_port}")
    elif config.DB_HOST:
        db_host = config.DB_HOST
        db_user = config.DB_USER
        db_password = config.DB_PASSWORD
        db_name = config.DB_NAME
        db_port = config.DB_PORT
    else:
        _log("❌ DB 연결 정보가 없습니다.")
        _log("   Railway 환경에서는 Cron Job 서비스의 Variables에 다음을 추가하세요:")
        _log("   MYSQLHOST = ${{ MySQL.MYSQLHOST }}")
        _log("   MYSQLUSER = ${{ MySQL.MYSQLUSER }}")
        _log("   MYSQLPASSWORD = ${{ MySQL.MYSQLPASSWORD }}")
        _log("   MYSQLDATABASE = ${{ MySQL.MYSQLDATABASE }}")
        _log("   MYSQLPORT = ${{ MySQL.MYSQLPORT }}")
        return 0

    import time
    
    max_retries = 3
    conn = None
    for attempt in range(1, max_retries + 1):
        try:
            conn = mysql.connector.connect(
                host=db_host,
                port=db_port,
                user=db_user,
                password=db_password,
                database=db_name,
                charset="utf8mb4",
                connection_timeout=10,
            )
            break
        except mysql.connector.errors.OperationalError as e:
            _log(f"⚠️ DB 연결 실패 (시도 {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                wait = attempt * 5  # 5초, 10초, 15초
                _log(f"   {wait}초 후 재시도...")
                time.sleep(wait)
            else:
                _log("❌ DB 연결 최종 실패. 모든 재시도 소진.")
                return 0
    
    if conn is None:
        return 0
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

    rows_to_insert = []
    skipped_identical = 0
    for r in rows:
        if _is_same_as_latest_row(cur, r):
            skipped_identical += 1
            continue
        rows_to_insert.append(r)

    if skipped_identical:
        _log(f"Skipped identical rows vs latest DB state: {skipped_identical}")

    if not rows_to_insert:
        _log("No changed/new rows to insert.")
        cur.close()
        conn.close()
        return 0

    data = []
    for r in rows_to_insert:
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


def update_card_image_paths(rows, *, snapshot_id: str):
    """
    이미 저장된 동일 snapshot 행에 card_image_path만 후반 업데이트한다.
    (DB 저장 선행 -> 카드 렌더/S3 후처리용)
    """
    rows_with_cards = [r for r in rows if _norm_text(r.get("card_image_path"))]
    if not rows_with_cards:
        return 0

    import os
    import time

    if os.getenv("MYSQLHOST"):
        db_host = os.getenv("MYSQLHOST")
        db_user = os.getenv("MYSQLUSER")
        db_password = os.getenv("MYSQLPASSWORD")
        db_name = os.getenv("MYSQLDATABASE")
        db_port = int(os.getenv("MYSQLPORT", 3306))
    elif config.DB_HOST:
        db_host = config.DB_HOST
        db_user = config.DB_USER
        db_password = config.DB_PASSWORD
        db_name = config.DB_NAME
        db_port = config.DB_PORT
    else:
        _log("⚠️ DB 연결 정보가 없어 card_image_path 후반 업데이트를 건너뜁니다.")
        return 0

    max_retries = 3
    conn = None
    for attempt in range(1, max_retries + 1):
        try:
            conn = mysql.connector.connect(
                host=db_host,
                port=db_port,
                user=db_user,
                password=db_password,
                database=db_name,
                charset="utf8mb4",
                connection_timeout=10,
            )
            break
        except mysql.connector.errors.OperationalError as e:
            _log(f"⚠️ DB 재연결 실패(카드 경로 업데이트, 시도 {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                time.sleep(attempt * 2)
            else:
                _log("⚠️ card_image_path 업데이트를 포기하고 종료합니다.")
                return 0

    if conn is None:
        return 0

    cur = conn.cursor()
    updated = 0

    for r in rows_with_cards:
        card_image_path = _norm_text(r.get("card_image_path"))
        link = _norm_text(r.get("link"))

        if link:
            cur.execute(
                f"""
                UPDATE {config.DB_TABLE}
                SET card_image_path = %s
                WHERE snapshot_id = %s
                  AND link = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (card_image_path, snapshot_id, link),
            )
        else:
            cur.execute(
                f"""
                UPDATE {config.DB_TABLE}
                SET card_image_path = %s
                WHERE snapshot_id = %s
                  AND channel = %s
                  AND market = %s
                  AND mall_name = %s
                  AND product_name = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (
                    card_image_path,
                    snapshot_id,
                    _norm_text(r.get("channel")) or "naver",
                    _norm_text(r.get("market")) or "스마트스토어",
                    _norm_text(r.get("mall_name")),
                    _norm_text(r.get("product_name")),
                ),
            )
        updated += cur.rowcount

    conn.commit()
    cur.close()
    conn.close()
    return updated


def run_crawling():
    _log(f"START: {datetime.now(KST).isoformat(timespec='seconds')}")
    keyword = config.SEARCH_KEYWORD

    rows = get_naver_data_all(keyword)
    fetched_count = len(rows)
    rows = _dedupe_rows(rows)
    _log(f"Fetched: {fetched_count} rows")
    _log(f"Deduped: {len(rows)} rows (removed {fetched_count - len(rows)})")

    # 실행 단위 snapshot_id/snapshot_at (초 단위 + UUID)로 고정해 run 간 혼합 방지
    snapshot_at = datetime.now(KST).replace(microsecond=0)
    snapshot_id = f"{snapshot_at.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"

    inserted = save_to_db(rows, snapshot_id=snapshot_id, snapshot_at=snapshot_at)
    _log(f"DB inserted: {inserted}")

    if not config.ENABLE_AUTO_CARD_RENDER:
        _log("Auto card render/upload skipped: ENABLE_AUTO_CARD_RENDER is false")
        s3_uploaded = 0
    else:
        try:
            s3_uploaded = _upload_product_images_to_s3(rows, snapshot_id=snapshot_id)
        except Exception as e:
            # 카드 렌더/S3 업로드는 부가 기능이므로 실패해도 크롤링은 성공 처리한다.
            _log(f"⚠️ S3 card upload stage failed unexpectedly: {e}")
            s3_uploaded = 0

    if s3_uploaded:
        _log(f"S3 uploaded: {s3_uploaded}")
        db_updated_cards = update_card_image_paths(rows, snapshot_id=snapshot_id)
        _log(f"DB card_image_path updated: {db_updated_cards}")
    elif config.ENABLE_S3_UPLOAD:
        _log("S3 upload enabled but 0 files uploaded")

    _log(f"END: {datetime.now(KST).isoformat(timespec='seconds')}")


if __name__ == "__main__":
    run_crawling()
