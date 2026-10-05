# scripts/crawl_naver_brightdata.py
"""
네이버 쇼핑을 Bright Data 경유로 자체 크롤링한다.

배경:
    네이버가 검색 API(openapi.naver.com /v1/search/shop.json) 제공을 중단해
    쿠팡과 동일하게 Bright Data 기반 자체 수집으로 전환한다.

수집 경로:
    네이버 쇼핑 프론트가 쓰는 내부 JSON 엔드포인트를 Bright Data 한국 주거용
    프록시로 호출한다.

        GET https://search.shopping.naver.com/ns/v1/search/paged-products
              ?cursor=<n>&pageSize=<n>&query=<검색어>

    검증 결과(2026-09-27):
      - Bright Data 주거용(-country-kr)  → 200 OK, 전량(448/450건) 수집
      - Bright Data Scraping Browser     → 해외 IP라 네이버 로그인으로 리다이렉트/차단
      - 렌더링 페이지(/ns/search, /search/all) 크롤링 → "접속이 일시적으로 제한" 차단
    따라서 쿠팡처럼 브라우저를 띄우지 않고, 주거용 프록시 + JSON 호출로 간다.

저장 계약은 기존과 동일하다. crawl_naver.py의 수량분석/필터/DB 저장 로직을
그대로 재사용하므로 products 테이블 스키마와 대시보드는 변경이 필요 없다.

사용법:
    python -m scripts.crawl_naver_brightdata            # 수집 + DB 저장
    python -m scripts.crawl_naver_brightdata --dry-run  # 수집만 (DB 미저장)
    python -m scripts.crawl_naver_brightdata --no-proxy # 프록시 없이 (한국 IP에서 점검용)

인수인계 메모:
    fallback / 차단 대응
      1) detect_block()           — 차단 판정 기준
      2) build_fetch_backends()   — 수집 백엔드 목록 (residential → unlocker → direct)
      3) fetch_all_products()     — 페이지 단위 fallback, 전부 실패 시 NaverCrawlFailed
      4) check_completeness()     — total 대비 수집률 미달 시 저장 생략(기존 데이터 보존)
    자세한 내용은 각 함수의 docstring 참고.
"""
import argparse
import os
import time
import urllib.parse
import uuid
from datetime import datetime

import requests
import urllib3
from dotenv import load_dotenv

load_dotenv()            # .env  (DB 등)
load_dotenv("proxy.env")  # Bright Data 크리덴셜

import config
from scripts.crawl_naver import (
    KST,
    MANUAL_QUANTITY_PENDING_METHODS,
    _is_coupang_item,
    _is_allowed_coupang_libre2_title,
    _is_target_libre2_product,
    _log,
    _normalize_mall_name,
    _upload_product_images_to_s3,
    analyze_product,
    load_confirmed_qty_by_link_map,
    save_to_db,
    update_card_image_paths,
)

# ---------------------------------------------------------------- Bright Data
PROXY_SERVER = os.getenv("BRIGHT_DATA_PROXY")
PROXY_USERNAME = os.getenv("BRIGHT_DATA_USERNAME")
PROXY_PASSWORD = os.getenv("BRIGHT_DATA_PASSWORD")

# Bright Data 주거용 프록시는 TLS를 중계하므로 기본 CA 체인으로는 검증이 실패한다.
# 운영에서 검증을 켜려면 Bright Data 인증서를 내려받아 BRIGHT_DATA_CA_CERT 에 경로를 준다.
BRIGHT_DATA_CA_CERT = os.getenv("BRIGHT_DATA_CA_CERT")
VERIFY_TLS = os.getenv("NAVER_BD_VERIFY_TLS", "false").lower() == "true"

# ---------------------------------------------------------------- 수집 파라미터
NS_API = "https://search.shopping.naver.com/ns/v1/search/paged-products"
PAGE_SIZE = int(os.getenv("NAVER_PAGE_SIZE", "100"))       # 최대 100
MAX_PAGES = int(os.getenv("NAVER_MAX_PAGES", "20"))        # 안전장치
REQUEST_TIMEOUT = int(os.getenv("NAVER_REQUEST_TIMEOUT", "45"))
MAX_RETRIES = int(os.getenv("NAVER_MAX_RETRIES", "3"))
PAGE_SLEEP_SEC = float(os.getenv("NAVER_PAGE_SLEEP_SEC", "0.4"))

USER_AGENT = os.getenv(
    "NAVER_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
)

# 신규 엔드포인트는 카테고리를 한글명이 아닌 ID로 준다.
# 구 API의 valid_categories(혈당계/혈당측정기/당뇨관리용품/당뇨)에 대응하는 ID 화이트리스트.
# 실측(2026-09-27): sCatId=50002066 에 실제 리브레2 센서 170건이 모두 들어오고,
# 패치/커버/파우치 등 액세서리는 50002068 / 50001033 등 다른 ID로 떨어진다.
ALLOWED_SCAT_IDS = set(
    filter(None, os.getenv("NAVER_ALLOWED_SCAT_IDS", "50002066").split(","))
)
ALLOWED_MCAT_IDS = set(
    filter(None, os.getenv("NAVER_ALLOWED_MCAT_IDS", "50000065").split(","))
)

# 구 API 파이프라인과 동일한 액세서리 키워드 필터
ACCESSORY_KEYWORDS = [
    "스크린 프로텍터", "화면 보호", "보호필름", "보호 필름",
    "케이스", "커버", "파우치", "홀스터", "랜야드",
    "충전 케이블", "충전케이블", "USB 케이블",
    "스킨그립", "스킨 그립", "오버패치",
    "클립", "카라비너", "벨트 클립",
]

MIN_UNIT_PRICE = int(os.getenv("NAVER_MIN_UNIT_PRICE", "65000"))

if not VERIFY_TLS:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class BlockedError(RuntimeError):
    """네이버가 차단(비정상 응답)했다고 판단한 경우."""


def _tls_verify_option():
    if BRIGHT_DATA_CA_CERT:
        return BRIGHT_DATA_CA_CERT
    return VERIFY_TLS


def _build_proxies(session_id: str | None, *, server=None, username=None, password=None):
    """Bright Data 프록시 주소를 만든다.

    username 에 `-session-<id>` 를 붙이면 해당 세션 동안 같은 출구 IP를 유지한다.
    차단 시 session_id 를 새로 뽑으면 다른 IP로 갈아탄다.
    session_id=None 이면 세션 고정을 쓰지 않는다 (Web Unlocker 존 등).
    server/username/password 를 생략하면 기본(BRIGHT_DATA_*) 크리덴셜을 쓴다.
    """
    server = server or PROXY_SERVER
    username = username or PROXY_USERNAME
    password = password or PROXY_PASSWORD
    if not all((server, username, password)):
        return None
    if session_id:
        username = f"{username}-session-{session_id}"
    creds = f"{urllib.parse.quote(username)}:{urllib.parse.quote(password)}"
    host = server.split("://", 1)[-1]
    url = f"http://{creds}@{host}"
    return {"http": url, "https": url}


def _headers(keyword: str):
    enc = urllib.parse.quote(keyword)
    return {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": f"https://search.shopping.naver.com/ns/search?query={enc}",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }


def detect_block(resp) -> str:
    """차단/비정상 응답이면 사유 문자열, 정상이면 빈 문자열을 반환한다.

    [인수인계 seam]
      차단 유형이 늘어나면 여기에 조건을 추가한다. 현재까지 관측된 유형:
        - 418 + text/html  : 봇 판정 인터스티셜
        - 302 → nid.naver.com/nidlogin : 해외/의심 IP를 로그인으로 유도
        - 200 + html 본문에 "접속이 일시적으로 제한" : 쇼핑 서비스 차단 안내
    """
    ctype = resp.headers.get("content-type", "")

    if resp.status_code != 200:
        return f"status={resp.status_code}"
    if "json" not in ctype:
        return f"content-type={ctype[:40]!r} (JSON 아님)"

    if "nidlogin" in resp.url or "nid.naver.com" in resp.url:
        return "네이버 로그인으로 리다이렉트"

    body_head = resp.text[:2000]
    for marker in ("접속이 일시적으로 제한", "비정상적인 접근", "captcha"):
        if marker in body_head:
            return f"차단 안내문({marker})"
    return ""


def _fetch_page_via_proxy(
    keyword: str,
    cursor: int,
    *,
    proxy_cfg: dict | None,
    sticky_session: bool = True,
):
    """한 페이지를 가져온다. 차단이면 세션(IP)을 바꿔 재시도한다.

    proxy_cfg: {"server", "username", "password"} 또는 None(직접 호출)
    반환: (items, next_cursor, has_more, total)
    """
    enc = urllib.parse.quote(keyword)
    url = f"{NS_API}?cursor={cursor}&pageSize={PAGE_SIZE}&query={enc}"
    last_reason = ""

    for attempt in range(1, MAX_RETRIES + 1):
        proxies = None
        if proxy_cfg is not None:
            session_id = uuid.uuid4().hex[:10] if sticky_session else None
            proxies = _build_proxies(session_id, **proxy_cfg)

        t0 = time.time()
        try:
            resp = requests.get(
                url,
                headers=_headers(keyword),
                proxies=proxies,
                timeout=REQUEST_TIMEOUT,
                verify=_tls_verify_option() if proxies else True,
            )
        except Exception as e:
            last_reason = f"{type(e).__name__}: {e}"
            _log(f"    [RETRY {attempt}/{MAX_RETRIES}] 요청 실패: {last_reason}")
            if attempt < MAX_RETRIES:
                time.sleep(attempt * 2)
            continue

        elapsed = time.time() - t0
        reason = detect_block(resp)
        if reason:
            last_reason = reason
            _log(f"    [RETRY {attempt}/{MAX_RETRIES}] 차단 감지: {reason} ({elapsed:.1f}s)")
            if attempt < MAX_RETRIES:
                time.sleep(attempt * 2)
            continue

        try:
            data = resp.json()["data"]
        except Exception as e:
            last_reason = f"응답 파싱 실패: {e}"
            _log(f"    [RETRY {attempt}/{MAX_RETRIES}] {last_reason}")
            if attempt < MAX_RETRIES:
                time.sleep(attempt * 2)
            continue

        items = data.get("data") or []
        # 첫 페이지가 정상 JSON 인데 0건이면 '소프트 차단'으로 본다.
        # (리브레2 검색 결과는 항상 수백 건이라 0건은 정상 상황이 아님)
        if cursor == 1 and not items:
            last_reason = f"첫 페이지 0건(total={data.get('total')}) — 소프트 차단 의심"
            _log(f"    [RETRY {attempt}/{MAX_RETRIES}] {last_reason}")
            if attempt < MAX_RETRIES:
                time.sleep(attempt * 2)
            continue

        _log(
            f"  page cursor={cursor} items={len(items)} "
            f"total={data.get('total')} {elapsed:.1f}s"
        )
        return items, data.get("cursor"), bool(data.get("hasMore")), data.get("total")

    raise BlockedError(f"cursor={cursor} {MAX_RETRIES}회 재시도 실패: {last_reason}")


# ------------------------------------------------------------ fallback 백엔드
class NaverCrawlFailed(RuntimeError):
    """모든 백엔드가 실패했거나 수집 결과가 불완전해 저장하면 안 되는 경우."""


def _env_proxy_cfg(prefix: str, *, default_server: str | None = None):
    """{prefix}_PROXY / _USERNAME / _PASSWORD 로 프록시 설정을 만든다. 없으면 None."""
    server = os.getenv(f"{prefix}_PROXY") or default_server
    username = os.getenv(f"{prefix}_USERNAME")
    password = os.getenv(f"{prefix}_PASSWORD")
    if not all((server, username, password)):
        return None
    return {"server": server, "username": username, "password": password}


def _make_proxy_backend(proxy_cfg, *, sticky_session: bool):
    def fetch_page(keyword, cursor):
        return _fetch_page_via_proxy(
            keyword, cursor, proxy_cfg=proxy_cfg, sticky_session=sticky_session
        )
    return fetch_page


def _fetch_page_direct(keyword, cursor):
    return _fetch_page_via_proxy(keyword, cursor, proxy_cfg=None)


# [인수인계 seam] 수집 백엔드 목록.
# NAVER_FETCH_BACKENDS 순서대로 시도하고, 설정(크리덴셜)이 없는 백엔드는 건너뛴다.
#   residential : Bright Data 주거용 KR (기본, proxy.env 의 BRIGHT_DATA_*)
#   unlocker    : Bright Data 다른 존(Web Unlocker 등) — BRIGHT_DATA_FALLBACK_*
#   direct      : 프록시 없이 직접 호출. 서버가 한국 IP일 때만 의미가 있어
#                 NAVER_ALLOW_DIRECT=true 일 때만 켠다 (Railway 는 해외 IP라 기본 OFF).
DEFAULT_BACKEND_ORDER = "residential,unlocker,direct"


def build_fetch_backends(*, use_proxy: bool = True):
    """설정된 백엔드만 (이름, fetch_page(keyword, cursor)) 리스트로 반환한다."""
    if not use_proxy:
        return [("direct", _fetch_page_direct)]

    order = [
        b.strip().lower()
        for b in os.getenv("NAVER_FETCH_BACKENDS", DEFAULT_BACKEND_ORDER).split(",")
        if b.strip()
    ]
    allow_direct = os.getenv("NAVER_ALLOW_DIRECT", "false").lower() == "true"

    backends = []
    for name in order:
        if name == "residential":
            cfg = _env_proxy_cfg("BRIGHT_DATA")
            if cfg:
                backends.append(
                    ("brightdata-residential-kr", _make_proxy_backend(cfg, sticky_session=True))
                )
            else:
                _log("[NAVER] residential 백엔드 건너뜀: BRIGHT_DATA_* 크리덴셜 없음")
        elif name == "unlocker":
            cfg = _env_proxy_cfg("BRIGHT_DATA_FALLBACK", default_server=PROXY_SERVER)
            if cfg:
                # Web Unlocker 존은 자체적으로 IP를 돌리므로 session 고정을 쓰지 않는다.
                sticky = os.getenv("BRIGHT_DATA_FALLBACK_STICKY", "false").lower() == "true"
                backends.append(
                    ("brightdata-fallback-zone", _make_proxy_backend(cfg, sticky_session=sticky))
                )
        elif name == "direct":
            if allow_direct:
                backends.append(("direct", _fetch_page_direct))
        else:
            _log(f"[WARN] 알 수 없는 백엔드 이름 무시: {name!r}")

    if not backends:
        raise NaverCrawlFailed(
            "사용 가능한 수집 백엔드가 없습니다. proxy.env 의 BRIGHT_DATA_* 크리덴셜을 확인하세요."
        )
    return backends


def fetch_all_products(keyword: str, *, use_proxy: bool = True, backends=None):
    """커서 페이지네이션으로 검색 결과를 전량 수집한다.

    fallback 규칙
      - 페이지 단위로 시도한다. 현재 백엔드가 재시도까지 모두 실패(BlockedError)하면
        다음 백엔드로 넘어가 '같은 cursor'부터 이어서 수집한다.
      - 한 번 넘어간 뒤에는 이전 백엔드로 돌아가지 않는다 (차단된 경로 재시도 방지).
      - 모든 백엔드가 실패하면 NaverCrawlFailed — 부분 수집분은 저장하지 않는다.

    반환: (items, meta)  meta = {"total", "pages", "backends_used"}
    """
    backends = backends if backends is not None else build_fetch_backends(use_proxy=use_proxy)
    _log("[NAVER] 수집 백엔드 순서: " + " → ".join(n for n, _ in backends))

    idx = 0
    items = []
    cursor = 1
    pages = 0
    total = None
    used = []  # 페이지별 사용 백엔드 (로그/점검용)
    failures = []

    while pages < MAX_PAGES:
        name, fetch_page = backends[idx]
        try:
            batch, next_cursor, has_more, total = fetch_page(keyword, cursor)
        except BlockedError as e:
            failures.append(f"{name}: {e}")
            _log(f"[NAVER] 백엔드 실패 {name}: {e}")
            idx += 1
            if idx >= len(backends):
                raise NaverCrawlFailed(
                    f"모든 백엔드 실패 (수집 {len(items)}건에서 중단): " + " | ".join(failures)
                ) from e
            _log(f"[NAVER] fallback → {backends[idx][0]} (cursor={cursor}부터 이어서)")
            continue

        items.extend(batch)
        used.append(name)
        pages += 1

        if not has_more or not batch:
            break
        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
        time.sleep(PAGE_SLEEP_SEC)

    if pages >= MAX_PAGES:
        _log(f"[WARN] MAX_PAGES({MAX_PAGES}) 도달 — 수집이 잘렸을 수 있음")

    backends_used = sorted(set(used), key=used.index)
    _log(
        f"[NAVER] 수집 완료: {len(items)}건 (total={total}, pages={pages}, "
        f"backends={','.join(backends_used)})"
    )
    return items, {"total": total, "pages": pages, "backends_used": backends_used}


def check_completeness(items, total) -> None:
    """수집 건수가 네이버가 알려준 total 대비 너무 적으면 저장을 막는다.

    부분 수집분으로 스냅샷을 만들면 대시보드에서 판매처/상품이 '사라진' 것처럼 보이므로,
    이 경우 기존 DB 데이터를 그대로 두는 편이 안전하다.
    """
    min_ratio = float(os.getenv("NAVER_MIN_COMPLETENESS", "0.9"))
    if not total:
        return
    ratio = len(items) / total
    if ratio < min_ratio:
        raise NaverCrawlFailed(
            f"수집 불완전: {len(items)}/{total}건 ({ratio:.0%} < {min_ratio:.0%}) — 저장 생략"
        )


def _passes_category(item) -> bool:
    scat = str(item.get("sCatId") or "")
    mcat = str(item.get("mCatId") or "")
    return scat in ALLOWED_SCAT_IDS or mcat in ALLOWED_MCAT_IDS


def _is_accessory(title: str) -> bool:
    import re

    low = title.lower()
    if not any(kw.lower() in low for kw in ACCESSORY_KEYWORDS):
        return False
    # 단, "센서 n개/팩/세트/박스"가 상품명에 있으면 본품으로 본다 (구 로직과 동일)
    return not re.search(r"센서\s*\d+\s*(개|팩|세트|박스)", title)


def build_rows(items, keyword: str, confirmed_qty_by_link=None):
    """수집 결과를 products 테이블 행 형태로 정규화·필터링한다.

    구 get_naver_data_all() 의 필터 순서를 그대로 따른다.
    """
    stats = {
        "non_target": 0, "category": 0, "accessory": 0, "coupang_title": 0,
        "no_price": 0, "qty_pending": 0, "under_min_unit": 0, "kept": 0,
    }
    rows = []

    for item in items:
        title = (item.get("productName") or "").strip()
        if not _is_target_libre2_product(title):
            stats["non_target"] += 1
            continue

        if not _passes_category(item):
            stats["category"] += 1
            continue

        if _is_accessory(title):
            stats["accessory"] += 1
            continue

        # 실판매가 우선, 없으면 정가
        total_price = int(item.get("discountedSalePrice") or item.get("salePrice") or 0)
        if total_price <= 0:
            stats["no_price"] += 1
            continue

        link = (item.get("productUrl") or {}).get("pcUrl") or ""
        mall = (item.get("mallName") or "").strip()
        if mall == "네이버":
            mall = "최저가비교"
        mall = _normalize_mall_name(mall)

        channel = "naver"
        market = "스마트스토어"
        if _is_coupang_item(link, mall):
            if not _is_allowed_coupang_libre2_title(title):
                stats["coupang_title"] += 1
                continue
            channel = "coupang"
            market = "마켓플레이스"

        qty, unit_price, method = analyze_product(
            title, total_price, link, confirmed_qty_by_link
        )

        if method in MANUAL_QUANTITY_PENDING_METHODS:
            stats["qty_pending"] += 1
            continue
        if unit_price < MIN_UNIT_PRICE:
            stats["under_min_unit"] += 1
            continue

        images = item.get("images") or []
        rows.append({
            "keyword": keyword,
            "product_name": title,
            "unit_price": unit_price,
            "quantity": qty,
            "total_price": total_price,
            "mall_name": mall,
            "calc_method": method,
            "link": link,
            "image_url": images[0].get("imageUrl") if images else "",
            "card_image_path": None,
            "channel": channel,
            "market": market,
        })
        stats["kept"] += 1

    _log(
        "[NAVER] 필터 결과: "
        + " ".join(f"{k}={v}" for k, v in stats.items())
    )
    return rows


def run_crawling(*, use_proxy: bool = True, dry_run: bool = False):
    """크롤링 → DB 저장 → 카드 렌더/S3 업로드.

    crawl_naver.run_crawling() 과 동일한 orchestration 이라 호출부는 교체만 하면 된다.
    """
    crawl_started_at = datetime.now(KST).replace(microsecond=0)
    _log(f"START NAVER (Bright Data): {crawl_started_at.isoformat(timespec='seconds')}")
    keyword = config.SEARCH_KEYWORD

    confirmed_map = load_confirmed_qty_by_link_map() if not dry_run else {}
    if confirmed_map:
        _log(f"수동확정 수량 재사용 맵: {len(confirmed_map)}개 링크")

    # 실패 시 예외를 올려 /crawl/status 의 last_error 에 남게 한다. (기존 DB 데이터는 보존)
    items, meta = fetch_all_products(keyword, use_proxy=use_proxy)
    if not items:
        raise NaverCrawlFailed("수집 0건 — 차단 가능성. DB 저장을 건너뜁니다.")
    check_completeness(items, meta["total"])

    rows = build_rows(items, keyword, confirmed_qty_by_link=confirmed_map)
    _log(f"Fetched: {len(rows)} rows")

    if dry_run:
        _log("[DRY-RUN] DB 저장 생략")
        rows.sort(key=lambda r: r["unit_price"])
        for r in rows[:15]:
            flag = "★" if r["unit_price"] <= config.TARGET_PRICE else " "
            _log(
                f"  {flag} {r['unit_price']:>8,}원/개 x{r['quantity']} "
                f"총{r['total_price']:>9,} [{r['mall_name'][:10]}] "
                f"{r['product_name'][:40]}"
            )
        below = sum(1 for r in rows if r["unit_price"] <= config.TARGET_PRICE)
        _log(f"[DRY-RUN] 기준가({config.TARGET_PRICE:,}원) 이하 {below}/{len(rows)}건")
        return

    if not rows:
        raise NaverCrawlFailed(
            f"필터 통과 0건 (수집 {len(items)}건) — 응답 구조/카테고리 ID 변경 여부 확인 필요"
        )

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


def main():
    ap = argparse.ArgumentParser(description="네이버 쇼핑 Bright Data 크롤러")
    ap.add_argument("--dry-run", action="store_true", help="DB 저장 없이 수집만")
    ap.add_argument("--no-proxy", action="store_true",
                    help="Bright Data 없이 직접 호출 (한국 IP 점검용)")
    args = ap.parse_args()
    try:
        run_crawling(use_proxy=not args.no_proxy, dry_run=args.dry_run)
    except NaverCrawlFailed as e:
        _log(f"[ERROR] {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
