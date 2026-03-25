# scripts/crawl_coupang.py
import os
import time
import re
import hmac
import hashlib
import csv
from datetime import datetime
from urllib.parse import quote

import requests
import config

DOMAIN = "https://api-gateway.coupang.com"
PATH = "/v2/providers/affiliate_open_api/apis/openapi/products/search"

DEBUG = os.getenv("COUPANG_DEBUG", "1") == "1"

# 문서: limit 최대 10
COUPANG_LIMIT = int(os.getenv("COUPANG_LIMIT", "10"))
COUPANG_LIMIT = max(1, min(10, COUPANG_LIMIT))

# 옵션 (선택)
COUPANG_SUB_ID = os.getenv("COUPANG_SUB_ID")
COUPANG_IMAGE_SIZE = os.getenv("COUPANG_IMAGE_SIZE")  # 예: "512x512"
COUPANG_SRP_LINK_ONLY = os.getenv("COUPANG_SRP_LINK_ONLY")  # "true"/"false"

# 키워드 세트 (환경변수로도 넣을 수 있게)
# 예: $env:COUPANG_KEYWORDS="프리스타일 리브레2|프리스타일 리브레2 센서|리브레2 센서"
DEFAULT_KEYWORDS = [
    "프리스타일 리브레2",
    "프리스타일 리브레2 센서",
    "리브레2 센서",
    "애보트 리브레2",
    "연속혈당측정기 리브레2",
    "프리스타일 리브레 2 센서",
    "Freestyle Libre 2 sensor",
]

COUPANG_KEYWORDS_ENV = os.getenv("COUPANG_KEYWORDS")
KEYWORDS = (
    [k.strip() for k in COUPANG_KEYWORDS_ENV.split("|") if k.strip()]
    if COUPANG_KEYWORDS_ENV
    else DEFAULT_KEYWORDS
)

# 호출 간격(레이트리밋 여유)
SLEEP_SEC = float(os.getenv("COUPANG_SLEEP_SEC", "1.3"))

# ✅ 기준 단가 필터 유지(85000 이하)
TARGET_UNIT_PRICE = int(os.getenv("TARGET_UNIT_PRICE", "85000"))

LIBRE2_INCLUDE_PATTERNS = [
    r"프리스타일\s*리브레\s*2",
    r"리브레\s*2",
    r"freestyle\s*libre\s*2",
    r"libre\s*2",
]

NON_LIBRE_CGM_EXCLUDE_PATTERNS = [
    r"덱스콤",
    r"dexcom",
    r"\bg\s*7\b",
    r"\bg7\b",
    r"가디언",
    r"guardian",
    r"케어센스\s*에어",
]


def _auth_header(method: str, url_path_with_query: str) -> str:
    path, *query = url_path_with_query.split("?")
    signed_date = time.strftime("%y%m%dT%H%M%SZ", time.gmtime())
    message = signed_date + method + path + (query[0] if query else "")

    signature = hmac.new(
        (config.COUPANG_SECRET_KEY or "").encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return f"CEA algorithm=HmacSHA256, access-key={config.COUPANG_ACCESS_KEY}, signed-date={signed_date}, signature={signature}"


def _is_accessory(title: str) -> bool:
    """
    ✅ 규칙:
    - 악세서리 키워드가 없으면: False (삭제 안 함)
    - 악세서리 키워드가 있으면:
        - '+'(플러스) 기호가 있으면: False (사은품/구성품으로 보고 삭제 안 함)
        - '+' 기호가 없으면: True (악세서리 단독으로 보고 삭제)
    """
    t = (title or "").lower()

    accessory_patterns = [
        r"패치", r"오버\s*패치", r"오버패치", r"\bpatch\b", r"\boverpatch\b",
        r"커버", r"\bcover\b", r"케이스", r"\bcase\b",
        r"보호\s*필름", r"보호필름", r"필름", r"\bfilm\b",
        r"프로텍터", r"\bprotector\b", r"\bscreen\b",
        r"스트랩", r"\bstrap\b", r"밴드", r"\bband\b",
        r"홀더", r"\bholder\b", r"클립", r"\bclip\b",
        r"스티커", r"\bsticker\b", r"테이프", r"\btape\b",
        r"접착", r"\badhesive\b",
    ]

    has_accessory = any(re.search(p, t, re.IGNORECASE) for p in accessory_patterns)
    if not has_accessory:
        return False  # 악세서리 단어 없으면 통과

    # '+' 기호(전각 포함) 있으면 사은품/구성품 포함으로 보고 통과
    if ("+" in title) or ("＋" in title):
        return False

    # 악세서리 단어 있는데 '+' 없으면 악세서리 단독 판매로 보고 제외
    return True


def _is_target_libre2_product(title: str) -> bool:
    text = (title or "").strip()
    if not text:
        return False

    if any(re.search(pattern, text, re.IGNORECASE) for pattern in NON_LIBRE_CGM_EXCLUDE_PATTERNS):
        return False

    return any(re.search(pattern, text, re.IGNORECASE) for pattern in LIBRE2_INCLUDE_PATTERNS)


def analyze_product(title: str, total_price: int):
    clean_title = title or ""

    gift_patterns = [
        r"사은품[^+]*", r"증정[^+]*",
        r"\+\s*패치\s*\d+\s*(개|매|장)?",
        r"\+\s*알콜\s*(솜|스왑|스웹)?\s*\d+\s*(개|매|장)?",
    ]
    for p in gift_patterns:
        clean_title = re.sub(p, " ", clean_title, flags=re.IGNORECASE)

    sensor_qty_patterns = [
        r"(측정기|센서|리브레\s*2?)\s*(\d+)\s*(개|개입|세트|팩|박스)",
        r"(\d+)\s*(개|개입|세트|팩|박스)\s*(측정기|센서)",
        r"(측정기|센서|리브레)\s*[xX*]\s*(\d+)",
    ]

    sensor_qty = None
    qty_from_text = False

    for pattern in sensor_qty_patterns:
        m = re.search(pattern, clean_title, re.IGNORECASE)
        if m:
            for g in m.groups():
                if g and str(g).isdigit():
                    sensor_qty = int(g)
                    break
            if sensor_qty:
                qty_from_text = True
                break

    if sensor_qty is None:
        candidates = []
        matches = re.findall(r"[\s](\d+)\s*(개|개입|세트|팩|박스|ea|set)", clean_title, re.IGNORECASE)
        for x in matches:
            candidates.append(int(x[0]))
        matches_mul = re.findall(r"[xX*]\s*(\d+)", clean_title)
        for x in matches_mul:
            candidates.append(int(x))

        if candidates:
            sensor_qty = candidates[0]
            qty_from_text = True
        else:
            sensor_qty = 1
            qty_from_text = False

    unit_price = total_price // sensor_qty if sensor_qty > 0 else total_price
    how = "텍스트분석" if qty_from_text else "기본(1개)"
    return sensor_qty, unit_price, how


def fetch_coupang_products(keyword: str, limit: int):
    if not config.COUPANG_ACCESS_KEY or not config.COUPANG_SECRET_KEY:
        raise RuntimeError("COUPANG_ACCESS_KEY / COUPANG_SECRET_KEY 환경변수가 필요합니다.")

    q = [f"keyword={quote(keyword)}", f"limit={max(1, min(10, limit))}"]
    if COUPANG_SUB_ID:
        q.append(f"subId={quote(COUPANG_SUB_ID)}")
    if COUPANG_IMAGE_SIZE:
        q.append(f"imageSize={quote(COUPANG_IMAGE_SIZE)}")
    if COUPANG_SRP_LINK_ONLY:
        q.append(f"srpLinkOnly={quote(COUPANG_SRP_LINK_ONLY)}")

    query = "&".join(q)

    url_path_with_query = f"{PATH}?{query}"
    url = f"{DOMAIN}{url_path_with_query}"
    auth = _auth_header("GET", url_path_with_query)

    if DEBUG:
        print("\n🔎 COUPANG REQUEST")
        print("  keyword:", keyword)
        print("  url:", url)

    r = requests.get(
        url,
        headers={
            "Authorization": auth,
            "Content-Type": "application/json;charset=UTF-8",
        },
        timeout=20,
    )

    if DEBUG:
        print("🔎 COUPANG RESPONSE")
        print("  http_status:", r.status_code)
        print("  text(head):", (r.text or "")[:200])

    r.raise_for_status()
    raw = r.json()

    if str(raw.get("rCode")) != "0":
        raise RuntimeError(f"Coupang API error: rCode={raw.get('rCode')} rMessage={raw.get('rMessage')}")

    return raw


def _save_csv(path: str, rows: list, fieldnames: list):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_crawling():
    print(f"START: {datetime.now().isoformat(timespec='seconds')}")

    kw_env = os.getenv("COUPANG_KEYWORDS")
    if kw_env:
        keywords = [k.strip() for k in kw_env.split("|") if k.strip()]
    else:
        keywords = KEYWORDS

    # ✅ 총 호출 횟수(기본 50회)
    CALLS = int(os.getenv("COUPANG_CALLS", "50"))
    SLEEP_SEC = float(os.getenv("COUPANG_SLEEP_SEC", "1.3"))

    TARGET = int(os.getenv("TARGET_UNIT_PRICE", "85000"))
    USE_TARGET = os.getenv("USE_TARGET_FILTER", "1") == "1"

    print(f"KEYWORDS({len(keywords)}): {keywords}")
    print(f"calls={CALLS}, limit={COUPANG_LIMIT}, target<={TARGET} ({'ON' if USE_TARGET else 'OFF'})")

    seen = set()

    # ✅ CSV로 볼 “필터 전(raw)”과 “필터 후(kept)” 모두 수집
    raw_rows = []
    kept_rows = []

    total_fetched = 0

    stat_dup = 0
    stat_accessory = 0
    stat_low_unit = 0
    stat_over_target = 0
    stat_non_target = 0
    stat_invalid = 0

    for i in range(1, CALLS + 1):
        kw = keywords[(i - 1) % len(keywords)]  # ✅ 키워드 라운드로빈

        raw = fetch_coupang_products(kw, limit=COUPANG_LIMIT)
        data = raw.get("data") or {}
        product_list = data.get("productData") or []

        total_fetched += len(product_list)

        new_kept = 0
        for p in product_list:
            pid = p.get("productId")
            title = p.get("productName") or ""
            total_price = int(p.get("productPrice") or 0)
            is_rocket = bool(p.get("isRocket"))
            link = p.get("productUrl") or ""
            image_url = p.get("productImage") or ""

            if not pid or not title or total_price <= 0:
                stat_invalid += 1
                continue

            # 중복 제거 (raw/kept 모두 같은 기준으로 보기 위해 여기서 제거)
            if pid in seen:
                stat_dup += 1
                continue
            seen.add(pid)

            # 단가/수량 계산은 raw에도 기록(나중에 엑셀에서 확인)
            qty, unit_price, how = analyze_product(title, total_price)

            # ✅ raw_rows: “중복 제거까지 된” 전체 후보를 저장
            raw_rows.append({
                "keyword": kw,
                "productId": pid,
                "title": title,
                "total_price": total_price,
                "quantity": qty,
                "unit_price": unit_price,
                "calc_method": how,
                "isRocket": is_rocket,
                "link": link,
                "image_url": image_url,
            })

            # ---- 아래부터 kept 필터 ----
            if _is_accessory(title):
                stat_accessory += 1
                continue

            if not _is_target_libre2_product(title):
                stat_non_target += 1
                continue

            if unit_price < 65000:
                stat_low_unit += 1
                continue

            if USE_TARGET and unit_price > TARGET:
                stat_over_target += 1
                continue

            kept_rows.append({
                "keyword": kw,
                "productId": pid,
                "product_name": title,
                "total_price": total_price,
                "quantity": qty,
                "unit_price": unit_price,
                "calc_method": how,
                "market": "로켓배송" if is_rocket else "마켓플레이스",
                "link": link,
                "image_url": image_url,
            })
            new_kept += 1

        print(f"[{i}/{CALLS}] kw='{kw}' fetched={len(product_list)} unique={len(seen)} kept={len(kept_rows)} (+{new_kept})")

        if i < CALLS:
            time.sleep(SLEEP_SEC)

    print("\nRESULT")
    print(f"calls={CALLS}, limit={COUPANG_LIMIT}, total_fetched={total_fetched}")
    print(f"unique_productIds={len(seen)}")
    print(f"kept_rows(unit<=target)={len(kept_rows)} (target={TARGET}, filter={'ON' if USE_TARGET else 'OFF'})")
    print(
        "excluded: "
        f"invalid={stat_invalid}, dup={stat_dup}, accessory={stat_accessory}, "
        f"non_target={stat_non_target}, unit<65000={stat_low_unit}, over_target={stat_over_target}"
    )

    # ✅ CSV 저장
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = f"coupang_raw_{ts}.csv"
    kept_path = f"coupang_kept_{ts}.csv"

    _save_csv(
        raw_path,
        raw_rows,
        fieldnames=[
            "keyword", "productId", "title", "total_price", "quantity", "unit_price",
            "calc_method", "isRocket", "link", "image_url"
        ],
    )
    _save_csv(
        kept_path,
        kept_rows,
        fieldnames=[
            "keyword", "productId", "product_name", "total_price", "quantity", "unit_price",
            "calc_method", "market", "link", "image_url"
        ],
    )

    print(f"\n✅ Saved RAW CSV  -> {raw_path}")
    print(f"✅ Saved KEPT CSV -> {kept_path}")

    # 콘솔 샘플 출력(원하면 유지)
    if kept_rows:
        print("\n✅ KEPT SAMPLE (top 20)")
        for i, row in enumerate(kept_rows[:20], start=1):
            print(f"[{i}] ({row['keyword']}) {row['product_name']}")
            print(f"    total={row['total_price']} qty={row['quantity']} unit={row['unit_price']} {row['market']}")
            print(f"    link: {row['link']}")

    print(f"END: {datetime.now().isoformat(timespec='seconds')}")


if __name__ == "__main__":
    run_crawling()