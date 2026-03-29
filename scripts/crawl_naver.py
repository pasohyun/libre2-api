import os
import urllib.request
import urllib.parse
import urllib.error
import json
import re
import time
import uuid
from html import unescape
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
COUPANG_SELLER_ENRICH_ENABLED = os.getenv("COUPANG_SELLER_ENRICH_ENABLED", "true").lower() == "true"
COUPANG_SELLER_TIMEOUT_SEC = int(os.getenv("COUPANG_SELLER_TIMEOUT_SEC", "8"))
# 쿠팡 상품 페이지 추가 조회는 런타임/트래픽 보호를 위해 상한을 둔다.
COUPANG_SELLER_MAX_FETCH_PER_RUN = int(os.getenv("COUPANG_SELLER_MAX_FETCH_PER_RUN", "30"))

MALL_NAME_NORMALIZE_MAP = {
    "글루어트": "글루코핏",
    "무화당": "닥다몰",
}

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

# 대시보드에서 수량확정(수동) 대상과 동일. DB에는 넣지 않으며 save_to_db 시 기존 동일 행도 삭제한다.
MANUAL_QUANTITY_PENDING_METHODS = frozenset(
    ("확인필요", "가격역산(보정)", "텍스트분석(범위초과)"),
)
_MANUAL_QUANTITY_PENDING_METHODS_SQL = (
    "확인필요",
    "가격역산(보정)",
    "텍스트분석(범위초과)",
)


def _log(message: str):
    # Cron 환경에서 출력 버퍼링으로 로그가 늦게 보이는 문제를 줄인다.
    print(message, flush=True)


def _normalize_mall_name(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return raw
    return MALL_NAME_NORMALIZE_MAP.get(raw, raw)


def _is_target_libre2_product(title: str) -> bool:
    text = (title or "").strip()
    if not text:
        return False

    # 덱스콤/가디언 등 타 CGM 모델을 먼저 제외한다.
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in NON_LIBRE_CGM_EXCLUDE_PATTERNS):
        return False

    return any(re.search(pattern, text, re.IGNORECASE) for pattern in LIBRE2_INCLUDE_PATTERNS)


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


def _fixed_quantity_for_product_link(link: str):
    """
    상품명 파싱이 반복 오판하는 특정 URL은 수량을 고정한다.
    (예: 옥션/지마켓 일부 상품이 사은품 문구 때문에 3개로 잡히는 경우)
    """
    if not (link or "").strip():
        return None
    try:
        u = urllib.parse.urlparse(link.strip())
        host = (u.netloc or "").lower()
        raw_qs = urllib.parse.parse_qs(u.query, keep_blank_values=True)
        q = {k.lower(): v for k, v in raw_qs.items()}

        if "auction.co.kr" in host:
            for v in q.get("itemno") or []:
                if str(v).strip().upper() == "F208273220":
                    return 2

        if "gmarket.co.kr" in host:
            for v in q.get("goodscode") or []:
                if str(v).strip() == "4407378380":
                    return 2
    except Exception:
        return None
    return None


def analyze_product(title, total_price, link=None):
    """
    상품명에서 센서 수량과 단가를 분석

    핵심: 센서/측정기 수량만 추출, 사은품(패치, 알콜솜 등)은 무시
    """
    fixed_qty = _fixed_quantity_for_product_link(link or "")
    if fixed_qty is not None and fixed_qty > 0:
        calc_unit_price = total_price // fixed_qty
        return fixed_qty, calc_unit_price, f"링크별수량고정({fixed_qty}개)"

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
        r"(측정기|센서|리브레\s*2?)\s*(\d+)\s*(개입|세트|팩|박스|개(?!\s*[인용]))",
        r"(\d+)\s*(개입|세트|팩|박스|개(?!\s*[인용]))\s*(측정기|센서)",
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

    def _extract_qty_candidates(text: str):
        qty_candidates = []

        matches = re.findall(
            r"[\s](\d+)\s*(개입|세트|팩|박스|ea|set|개(?!\s*[인용]))",
            text,
            re.IGNORECASE,
        )
        for m in matches:
            qty_candidates.append(int(m[0]))

        matches_mul = re.findall(r"[xX*]\s*(\d+)", text)
        for m in matches_mul:
            qty_candidates.append(int(m))

        # 지나치게 큰 값/0은 노이즈로 간주
        return [q for q in qty_candidates if 1 <= q <= 20]

    def _pick_best_qty(candidates, total_price_value, min_price, max_price):
        unique = sorted(set(candidates))
        if not unique:
            return None

        valid = []
        for q in unique:
            unit = total_price_value // q if q > 0 else total_price_value
            if min_price <= unit <= max_price:
                valid.append((q, unit))

        if valid:
            # 정상 단가 범위 중 90,000원에 가장 가까운 수량을 우선
            valid.sort(key=lambda x: (abs(x[1] - 90000), x[0]))
            return valid[0][0]

        # 범위를 만족하는 후보가 없으면 기존처럼 첫 후보 대신 최소 수량 사용
        return unique[0]

    # 3. 센서 수량을 못 찾으면 일반 패턴으로 추출
    if sensor_qty is None:
        qty_candidates = _extract_qty_candidates(clean_title)
        if not qty_candidates:
            # 사은품 제거 과정에서 메인 수량까지 지워지는 케이스 보정
            qty_candidates = _extract_qty_candidates(title)

        picked_qty = _pick_best_qty(qty_candidates, total_price, 65000, 180000)
        if picked_qty is not None:
            sensor_qty = picked_qty
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


def _is_coupang_item(link: str, mall_name: str) -> bool:
    link_text = (link or "").lower()
    mall_text = (mall_name or "").strip()
    return ("coupang.com" in link_text) or (mall_text == "쿠팡")


def _is_allowed_coupang_libre2_title(title: str) -> bool:
    """
    네이버 OpenAPI 결과 중 쿠팡 채널로 분류된 항목은
    아래 핵심 타이틀 패턴만 허용한다.
    - "애보트 프리스타일 리브레2 연속 혈당측정기 FreeStyle Libre 2 n개"
    """
    text = re.sub(r"\s+", " ", (title or "").strip())
    if not text:
        return False

    has_core_ko = "애보트 프리스타일 리브레2 연속 혈당측정기" in text
    has_core_en = re.search(r"freestyle\s*libre\s*2", text, re.IGNORECASE) is not None
    has_qty = re.search(r"\b\d+\s*개\b", text) is not None
    return has_core_ko and has_core_en and has_qty


def _decode_json_escaped_text(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        return json.loads(f'"{raw}"')
    except Exception:
        return raw


def _extract_coupang_seller_name_from_html(html_text: str) -> str:
    if not html_text:
        return ""

    patterns = [
        r'"vendorName"\s*:\s*"([^"]+)"',
        r'"sellerName"\s*:\s*"([^"]+)"',
        r'"seller"\s*:\s*"([^"]+)"',
        r'"storeName"\s*:\s*"([^"]+)"',
        # JSON-LD 형태: "seller":{"@type":"Organization","name":"..."}
        r'"seller"\s*:\s*\{[^{}]{0,300}?"name"\s*:\s*"([^"]+)"',
        # HTML 텍스트 형태: 판매자 : (주)xxxx
        r"판매자\s*[:：]\s*([^<\n\r]+)",
    ]

    blocked = {"쿠팡", "coupang", "로켓배송", "rocket"}

    for pattern in patterns:
        match = re.search(pattern, html_text, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = _decode_json_escaped_text(match.group(1))
        candidate = unescape(candidate).strip()
        candidate = re.sub(r"\s+", " ", candidate)
        if candidate and candidate.lower() not in blocked:
            return candidate
    return ""


def _fetch_coupang_seller_name(link: str, cache: dict, *, timeout_sec: int) -> str:
    target = (link or "").strip()
    if not target:
        return ""

    cached = cache.get(target)
    if cached is not None:
        return cached

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.coupang.com/",
    }

    try:
        req = urllib.request.Request(target, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            html_text = resp.read().decode("utf-8", errors="ignore")
        seller_name = _extract_coupang_seller_name_from_html(html_text)
        if not seller_name:
            _log(f"coupang seller enrich miss: no pattern matched ({target[:120]})")
    except urllib.error.HTTPError as e:
        _log(f"coupang seller enrich failed: HTTP {e.code} ({target[:120]})")
        seller_name = ""
    except urllib.error.URLError as e:
        _log(f"coupang seller enrich failed: URL error {e.reason} ({target[:120]})")
        seller_name = ""
    except Exception as e:
        _log(f"coupang seller enrich failed: {e} ({target[:120]})")
        seller_name = ""

    cache[target] = seller_name
    return seller_name


def _can_fetch_coupang_seller(fetch_count: int) -> bool:
    # <= 0 은 제한 없음으로 본다.
    if COUPANG_SELLER_MAX_FETCH_PER_RUN <= 0:
        return True
    return fetch_count < COUPANG_SELLER_MAX_FETCH_PER_RUN


def get_naver_data_all(query):
    enc = urllib.parse.quote(query)
    all_results = []
    start = 1
    display = 100
    coupang_seller_cache = {}
    coupang_seller_fetch_count = 0
    coupang_seller_hit_count = 0
    coupang_seller_limit_skipped = 0

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
            excluded_by_non_target = 0
            excluded_by_coupang_title = 0
            excluded_by_qty_pending = 0

            for item in items:
                title = item.get("title", "").replace("<b>", "").replace("</b>", "")
                if not _is_target_libre2_product(title):
                    excluded_by_non_target += 1
                    if VERBOSE_EXCLUDE_LOG:
                        _log(f"  ⛔ 제외 (비대상 상품): {title[:50]}...")
                    continue
                total_price = int(item.get("lprice", 0) or 0)
                image_url = item.get("image", "")
                mall = item.get("mallName", "")
                if (mall or "").strip() == "네이버":
                    mall = "최저가비교"
                mall = _normalize_mall_name(mall)
                link = item.get("link", "")
                channel = "naver"
                market = "스마트스토어"

                is_coupang = _is_coupang_item(link, mall)
                if is_coupang:
                    if not _is_allowed_coupang_libre2_title(title):
                        excluded_by_coupang_title += 1
                        if VERBOSE_EXCLUDE_LOG:
                            _log(f"  ⛔ 제외 (쿠팡 타이틀 패턴 불일치): {title[:70]}...")
                        continue
                    channel = "coupang"
                    market = "마켓플레이스"

                    can_try_enrich = (
                        COUPANG_SELLER_ENRICH_ENABLED
                        and (mall or "").strip() == "쿠팡"
                        and (
                            link in coupang_seller_cache
                            or _can_fetch_coupang_seller(coupang_seller_fetch_count)
                        )
                    )
                    if can_try_enrich:
                        is_new_fetch = link not in coupang_seller_cache
                        seller_name = _fetch_coupang_seller_name(
                            link,
                            coupang_seller_cache,
                            timeout_sec=COUPANG_SELLER_TIMEOUT_SEC,
                        )
                        if is_new_fetch:
                            coupang_seller_fetch_count += 1
                        if seller_name:
                            mall = _normalize_mall_name(seller_name)
                            coupang_seller_hit_count += 1
                    elif (
                        COUPANG_SELLER_ENRICH_ENABLED
                        and (mall or "").strip() == "쿠팡"
                        and link not in coupang_seller_cache
                    ):
                        coupang_seller_limit_skipped += 1

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

                qty, unit_price, method = analyze_product(title, total_price, link)

                if method in MANUAL_QUANTITY_PENDING_METHODS:
                    excluded_by_qty_pending += 1
                    if VERBOSE_EXCLUDE_LOG:
                        _log(
                            f"  ⛔ 제외 (수량 미확정·DB 미저장): {method} | {title[:50]}..."
                        )
                    continue

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
                    "channel": channel,
                    "market": market,
                })

            kept_now = len(all_results)
            _log(
                "page start="
                f"{start} fetched={len(items)} kept={kept_now - kept_before} "
                f"excluded_non_target={excluded_by_non_target} "
                f"excluded_coupang_title={excluded_by_coupang_title} "
                f"excluded_category={excluded_by_category} "
                f"excluded_accessory={excluded_by_accessory} "
                f"excluded_qty_pending={excluded_by_qty_pending} "
                f"kept_total={kept_now}"
            )

            start += display
            time.sleep(0.2)

        except Exception as e:
            _log(f"API error: {e}")
            break

    if COUPANG_SELLER_ENRICH_ENABLED:
        _log(
            "coupang seller enrich summary: "
            f"fetched={coupang_seller_fetch_count}, resolved={coupang_seller_hit_count}, "
            f"unresolved={max(coupang_seller_fetch_count - coupang_seller_hit_count, 0)}, "
            f"limit_skipped={coupang_seller_limit_skipped}, "
            f"cache_size={len(coupang_seller_cache)}"
        )

    return all_results


# ✅ (1) calc_valid 함수 추가
def _calc_valid(calc_method: str) -> int:
    cm = (calc_method or "").strip()
    if "확인" in cm or "범위초과" in cm:
        return 0
    return 1


def _norm_text(value) -> str:
    return (value or "").strip()


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

    try:
        cur.execute(
            f"DELETE FROM {config.DB_TABLE} WHERE calc_method IN (%s, %s, %s)",
            _MANUAL_QUANTITY_PENDING_METHODS_SQL,
        )
        purged = cur.rowcount
        conn.commit()
        if purged:
            _log(f"🗑️ 수량 미확정(calc_method) 행 DB 삭제: {purged}건")
    except Exception as e:
        _log(f"⚠️ 수량 미확정 행 삭제 실패(이번 저장은 중단): {e}")
        conn.rollback()
        cur.close()
        conn.close()
        return 0

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

    if not rows:
        _log("No rows to insert.")
        cur.close()
        conn.close()
        return 0

    data = []
    skipped_pending = 0
    for r in rows:
        cm = (r.get("calc_method") or "").strip()
        if cm in MANUAL_QUANTITY_PENDING_METHODS:
            skipped_pending += 1
            continue
        data.append(
            (
                r["keyword"],
                r["product_name"],
                r["unit_price"],
                r["quantity"],
                r["total_price"],
                _normalize_mall_name(r["mall_name"]),
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
    if skipped_pending:
        _log(f"⏭️ INSERT 생략(수량 미확정 calc_method): {skipped_pending}건")

    if not data:
        _log("No rows to insert after excluding 수량 미확정.")
        cur.close()
        conn.close()
        return 0

    cur.executemany(sql, data)
    inserted = cur.rowcount

    # 과거 데이터도 표준 판매처명으로 일괄 치환한다.
    updated_total = 0
    for old_name, new_name in MALL_NAME_NORMALIZE_MAP.items():
        cur.execute(
            f"UPDATE {config.DB_TABLE} SET mall_name = %s WHERE mall_name = %s",
            (new_name, old_name),
        )
        updated_total += cur.rowcount
    conn.commit()
    if updated_total > 0:
        _log(f"Mall names normalized in DB: {updated_total}")

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
    crawl_started_at = datetime.now(KST).replace(microsecond=0)
    _log(f"START: {crawl_started_at.isoformat(timespec='seconds')}")
    keyword = config.SEARCH_KEYWORD

    rows = get_naver_data_all(keyword)
    _log(f"Fetched: {len(rows)} rows")

    # 실행 단위 snapshot_id/snapshot_at (초 단위 + UUID)로 고정해 run 간 혼합 방지
    # snapshot_at은 "크롤링 시작 시각"으로 기록해 대시보드 표기 시 실행 시각과 맞춘다.
    snapshot_at = crawl_started_at
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
