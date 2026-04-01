import json
import os
import re
import sys
import time
import uuid
import random
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import requests
from bs4 import BeautifulSoup

import config
from scripts.crawl_naver import save_to_db


DEFAULT_URLS_FILE = BASE_DIR / "scripts" / "coupang_urls.json"

REQUEST_TIMEOUT = int(os.getenv("COUPANG_REQUEST_TIMEOUT", "60"))  # Scrapingbee는 응답이 느려서 넉넉하게
MIN_SLEEP_SEC = float(os.getenv("CRAWL_MIN_SLEEP_SEC", "0.5"))     # Scrapingbee가 알아서 우회하므로 짧게
MAX_SLEEP_SEC = float(os.getenv("CRAWL_MAX_SLEEP_SEC", "1.5"))

SCRAPINGBEE_API_KEY = os.getenv("SCRAPINGBEE_API_KEY", "")
SCRAPINGBEE_ENDPOINT = "https://app.scrapingbee.com/api/v1/"

ZENROWS_API_KEY = os.getenv("ZENROWS_API_KEY", "a72ab2d7e97d716a52e037e2b7d7377f3de0261d")
ZENROWS_ENDPOINT = "https://api.zenrows.com/v1/"

MAX_RETRY = 3
CONSECUTIVE_FAIL_LIMIT = 3

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


# ──────────────────────────────────────────────
# Scrapingbee 요청
# ──────────────────────────────────────────────

_ZENROWS_SESSION_ID = str(random.randint(10000, 99999))


def _is_bot_blocked(resp: requests.Response) -> bool:
    """Akamai 봇차단 페이지 여부 감지"""
    if resp.status_code != 200:
        return False
    text_lower = resp.text.lower()
    return "akamai" in text_lower or "powered and protected by privacy" in text_lower


def _fetch_via_zenrows(
    session: requests.Session, url: str, session_id: Optional[str] = None
) -> requests.Response:
    """
    Zenrows를 통해 URL을 가져옴. Akamai 우회에 특화.
    - session_id: 동일 세션 유지 → Akamai behavioral 분석 우회 핵심
    - 봇차단 감지 시 새 session_id로 1회 재시도
    """
    if not ZENROWS_API_KEY:
        raise RuntimeError("ZENROWS_API_KEY 환경변수가 설정되지 않았습니다.")

    sid = session_id or _ZENROWS_SESSION_ID

    params = {
        "apikey": ZENROWS_API_KEY,
        "url": url,
        "js_render": "true",
        "antibot": "true",
        "premium_proxy": "true",
        "session_id": sid,
    }

    resp = session.get(ZENROWS_ENDPOINT, params=params, timeout=REQUEST_TIMEOUT)

    # 봇차단 페이지 감지 → 새 session_id로 1회 재시도
    if _is_bot_blocked(resp):
        new_sid = str(random.randint(10000, 99999))
        print(f"  ⚠️ 봇차단 감지 (sid={sid}), 새 세션으로 재시도 (sid={new_sid})")
        params["session_id"] = new_sid
        resp = session.get(ZENROWS_ENDPOINT, params=params, timeout=REQUEST_TIMEOUT)

    return resp


# ──────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────

def _sleep_between_requests(idx: int):
    # Scrapingbee가 IP 관리를 해주므로 긴 휴식 불필요
    sleep_time = random.uniform(MIN_SLEEP_SEC, MAX_SLEEP_SEC)
    time.sleep(sleep_time)


def _dedupe_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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


def _canonicalize_coupang_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""

    parsed = urlparse(raw)
    query = parse_qs(parsed.query)

    item_id = query.get("itemId", [""])[0]
    vendor_item_id = query.get("vendorItemId", [""])[0]

    clean_query = {}
    if item_id:
        clean_query["itemId"] = item_id
    if vendor_item_id:
        clean_query["vendorItemId"] = vendor_item_id

    clean_path = parsed.path.rstrip("/") if parsed.path else ""
    if not clean_path:
        clean_path = parsed.path

    return urlunparse(
        (
            parsed.scheme or "https",
            parsed.netloc,
            clean_path,
            "",
            urlencode(clean_query),
            "",
        )
    )


def _load_target_urls() -> List[Dict[str, Any]]:
    file_path = Path(os.getenv("COUPANG_URLS_FILE", str(DEFAULT_URLS_FILE)))
    if not file_path.exists():
        raise FileNotFoundError(f"쿠팡 URL 목록 파일이 없습니다: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("coupang_urls.json 형식이 올바르지 않습니다. 리스트여야 합니다.")

    active_rows: List[Dict[str, Any]] = []
    seen_urls = set()

    for item in data:
        if isinstance(item, str):
            raw_url = item.strip()
            if not raw_url:
                continue
            url = _canonicalize_coupang_url(raw_url)
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            active_rows.append({"keyword": config.SEARCH_KEYWORD, "expected_name": "", "url": url})
            continue

        if isinstance(item, dict):
            if item.get("active", True) is False:
                continue
            raw_url = (item.get("url") or "").strip()
            if not raw_url:
                continue
            url = _canonicalize_coupang_url(raw_url)
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            active_rows.append(
                {
                    "keyword": item.get("keyword") or config.SEARCH_KEYWORD,
                    "expected_name": item.get("expected_name") or "",
                    "url": url,
                }
            )

    return active_rows


# ──────────────────────────────────────────────
# 파싱 헬퍼
# ──────────────────────────────────────────────

def _clean_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _is_target_libre2_product(title: str) -> bool:
    text = (title or "").strip()
    if not text:
        return False

    if any(re.search(pattern, text, re.IGNORECASE) for pattern in NON_LIBRE_CGM_EXCLUDE_PATTERNS):
        return False

    return any(re.search(pattern, text, re.IGNORECASE) for pattern in LIBRE2_INCLUDE_PATTERNS)


def _extract_meta_content(soup: BeautifulSoup, attrs: Dict[str, str]) -> str:
    tag = soup.find("meta", attrs=attrs)
    if not tag:
        return ""
    return _clean_text(tag.get("content", ""))


def _extract_text_first(soup: BeautifulSoup, selectors: List[str]) -> str:
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            text = _clean_text(node.get_text(" ", strip=True))
            if text:
                return text
    return ""


def _extract_attr_first(soup: BeautifulSoup, selectors: List[str], attr_name: str) -> str:
    for selector in selectors:
        node = soup.select_one(selector)
        if node and node.get(attr_name):
            return _clean_text(node.get(attr_name))
    return ""


def _parse_price_to_int(text_value: str) -> Optional[int]:
    if not text_value:
        return None
    digits = re.sub(r"[^\d]", "", text_value)
    if not digits:
        return None
    return int(digits)


def _extract_price(soup: BeautifulSoup) -> Optional[int]:
    # 현재 쿠팡 마크업 (2025~)
    selectors = [
        "div.final-price-amount",
        "div.price-amount",
        # 구 마크업 fallback
        "strong.total-price",
        "span.total-price",
        "strong.price-value",
        "span.price-value",
        "div.price-wrap strong",
        "div.prod-sale-price strong",
        "div.prod-price-container strong",
    ]
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            price = _parse_price_to_int(node.get_text(" ", strip=True))
            if price:
                return price

    meta_price = _extract_meta_content(soup, {"property": "product:price:amount"})
    if meta_price:
        parsed = _parse_price_to_int(meta_price)
        if parsed:
            return parsed

    html_text = soup.get_text(" ", strip=True)
    m = re.search(r"([0-9][0-9,]{3,})\s*원", html_text)
    if m:
        parsed = _parse_price_to_int(m.group(1))
        if parsed:
            return parsed

    return None


def _extract_product_name(soup: BeautifulSoup) -> str:
    candidates = [
        "h1.product-title",        # 현재 쿠팡 마크업 (2025~)
        "h1.prod-buy-header__title",
        "h2.prod-buy-header__title",
        "div.prod-buy-header h1",
        "h1",
    ]
    name = _extract_text_first(soup, candidates)
    if name:
        return name

    og_title = _extract_meta_content(soup, {"property": "og:title"})
    if og_title:
        # " - 쿠팡" 등 suffix 제거
        return re.sub(r"\s*[-|]\s*쿠팡\s*$", "", og_title).strip()

    title_tag = soup.find("title")
    if title_tag:
        return _clean_text(title_tag.get_text())

    return ""


def _extract_seller_name(soup: BeautifulSoup) -> str:
    # 현재 쿠팡 마크업: 판매자 정보 테이블에서 추출
    seller_table = soup.select_one("table.prod-delivery-return-policy-table")
    if seller_table:
        for tr in seller_table.find_all("tr"):
            th = tr.find("th")
            td = tr.find("td")
            if th and td and "판매자" in th.get_text():
                raw = td.get_text(" ", strip=True)
                # 전화번호 제거 (예: "쿠팡1577-7011" → "쿠팡")
                name = re.sub(r"\s*\d{2,4}-\d{3,4}-?\d{4}\s*", "", raw).strip()
                if name:
                    return name

    # 구 마크업 fallback
    candidates = [
        "a.prod-sale-vendor-name",
        "div.prod-sale-vendor a",
        "span.prod-sale-vendor-name",
        "div.prod-delivery-vendor-name",
    ]
    seller = _extract_text_first(soup, candidates)
    if seller:
        return seller

    return "쿠팡"


def _extract_image_url(soup: BeautifulSoup) -> str:
    candidates = [
        "img.prod-image__detail",
        "img.prod-image",
        "img[src]",
    ]
    src = _extract_attr_first(soup, candidates, "src")
    if src:
        return src

    og_image = _extract_meta_content(soup, {"property": "og:image"})
    if og_image:
        return og_image

    return ""


def _extract_stock_status(soup: BeautifulSoup) -> str:
    text_blob = soup.get_text(" ", strip=True)
    soldout_keywords = ["품절", "일시품절", "현재 판매중인 상품이 아닙니다", "재고가 없습니다"]
    for keyword in soldout_keywords:
        if keyword in text_blob:
            return "품절"
    return "판매중"


def _normalize_row(
    *,
    keyword: str,
    url: str,
    final_url: str,
    product_name: str,
    seller_name: str,
    price: Optional[int],
    stock_status: str,
    image_url: str,
) -> Optional[Dict[str, Any]]:
    if not product_name:
        return None
    if price is None or price <= 0:
        return None

    return {
        "keyword": keyword,
        "product_name": product_name,
        "unit_price": int(price),
        "quantity": 1,
        "total_price": int(price),
        "mall_name": seller_name or "쿠팡",
        "calc_method": "URL스냅샷",
        "link": final_url or url,
        "image_url": image_url,
        "card_image_path": None,
        "channel": "coupang",
        "market": "쿠팡",
    }


# ──────────────────────────────────────────────
# 크롤링 코어
# ──────────────────────────────────────────────

def crawl_one_url(session: requests.Session, item: Dict[str, Any]) -> Dict[str, Any]:
    url = item["url"]
    keyword = item.get("keyword") or config.SEARCH_KEYWORD

    for attempt in range(1, MAX_RETRY + 1):
        try:
            resp = _fetch_via_zenrows(session, url)
            status_code = resp.status_code

            # Scrapingbee 자체 에러 (4xx/5xx)
            if status_code == 401:
                raise RuntimeError("Scrapingbee API 키가 올바르지 않습니다.")
            if status_code == 429:
                wait = 10 * attempt
                print(f"  ⏳ Scrapingbee 요청 한도 초과, {wait}초 대기 후 재시도 ({attempt}/{MAX_RETRY})")
                time.sleep(wait)
                continue
            if status_code != 200:
                if attempt < MAX_RETRY:
                    wait = 5 * attempt
                    print(f"  ⏳ HTTP {status_code} 재시도 {attempt}/{MAX_RETRY}, {wait}초 대기")
                    time.sleep(wait)
                    continue
                return {
                    "ok": False,
                    "url": url,
                    "final_url": url,
                    "status_code": status_code,
                    "error": f"http_{status_code}",
                }

            soup = BeautifulSoup(resp.text, "lxml")

            product_name = _extract_product_name(soup)
            seller_name = _extract_seller_name(soup)
            image_url = _extract_image_url(soup)
            stock_status = _extract_stock_status(soup)
            price = _extract_price(soup)

            if not _is_target_libre2_product(product_name):
                return {
                    "ok": False,
                    "url": url,
                    "final_url": url,
                    "status_code": status_code,
                    "error": "non_target_product",
                    "product_name": product_name,
                    "seller_name": seller_name,
                }

            row = _normalize_row(
                keyword=keyword,
                url=url,
                final_url=url,
                product_name=product_name,
                seller_name=seller_name,
                price=price,
                stock_status=stock_status,
                image_url=image_url,
            )

            if not row:
                return {
                    "ok": False,
                    "url": url,
                    "final_url": url,
                    "status_code": status_code,
                    "error": "parse_failed",
                    "product_name": product_name,
                    "seller_name": seller_name,
                    "price": price,
                    "stock_status": stock_status,
                }

            row["stock_status"] = stock_status
            row["final_url"] = url

            return {
                "ok": True,
                "url": url,
                "final_url": url,
                "status_code": status_code,
                "row": row,
            }

        except RuntimeError:
            raise
        except requests.RequestException as e:
            if attempt == MAX_RETRY:
                return {"ok": False, "url": url, "final_url": url, "status_code": None, "error": f"request_error: {e}"}
            time.sleep(5 * attempt)
        except Exception as e:
            return {"ok": False, "url": url, "final_url": url, "status_code": None, "error": f"unexpected_error: {e}"}

    return {"ok": False, "url": url, "final_url": url, "status_code": None, "error": "max_retry_exceeded"}


def debug_one_url(url: str):
    session = requests.Session()
    resp = _fetch_via_zenrows(session, url)

    with open("debug_output.html", "w", encoding="utf-8") as f:
        f.write(resp.text)

    print("status_code:", resp.status_code)
    print("HTML 길이:", len(resp.text))
    print("파일 저장 완료: debug_output.html")


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────

def run_crawling():
    print(f"START COUPANG URL SNAPSHOT: {datetime.now().isoformat(timespec='seconds')}")

    if not ZENROWS_API_KEY:
        print("❌ ZENROWS_API_KEY 환경변수를 설정해주세요.")
        return

    target_urls = _load_target_urls()
    print(f"활성 URL 수(정규화/중복제거 후): {len(target_urls)}")
    print(f"예상 크레딧 소모: 최소 {len(target_urls)}개 (render_js=false 기준)")

    session = requests.Session()
    success_rows: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    consecutive_fail = 0

    for idx, item in enumerate(target_urls, start=1):
        print(f"[{idx}/{len(target_urls)}] {item['url']}")
        result = crawl_one_url(session, item)

        if result["ok"]:
            consecutive_fail = 0
            row = result["row"]
            success_rows.append(row)
            print(
                f"  ✅ success | 상품명={row['product_name'][:40]} | "
                f"판매자={row['mall_name']} | 가격={row['unit_price']:,}원"
            )
        else:
            failures.append(result)
            consecutive_fail += 1
            print(f"  ❌ fail | error={result.get('error')} | status={result.get('status_code')}")

            if consecutive_fail >= CONSECUTIVE_FAIL_LIMIT:
                print(f"연속 {CONSECUTIVE_FAIL_LIMIT}회 실패하여 실행을 중단합니다.")
                break

        if idx < len(target_urls):
            _sleep_between_requests(idx)

    fetched_count = len(success_rows)
    success_rows = _dedupe_rows(success_rows)
    print(f"성공 row 수: {fetched_count}")
    print(f"중복 제거 후 row 수: {len(success_rows)}")

    snapshot_at = datetime.now().replace(microsecond=0)
    snapshot_id = f"{snapshot_at.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"

    inserted = 0
    if success_rows:
        inserted = save_to_db(success_rows, snapshot_id=snapshot_id, snapshot_at=snapshot_at)

    print(f"DB inserted: {inserted}")
    print(f"실패 건수: {len(failures)}")

    if failures:
        fail_log_dir = BASE_DIR / "logs"
        fail_log_dir.mkdir(exist_ok=True)
        fail_log_path = fail_log_dir / f"coupang_failures_{snapshot_id}.json"
        with open(fail_log_path, "w", encoding="utf-8") as f:
            json.dump(failures, f, ensure_ascii=False, indent=2)
        print(f"실패 로그 저장: {fail_log_path}")

    print(f"END COUPANG URL SNAPSHOT: {datetime.now().isoformat(timespec='seconds')}")


if __name__ == "__main__":
    run_crawling()