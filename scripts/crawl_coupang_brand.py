# scripts/crawl_coupang_brand.py
"""
쿠팡 브랜드 스토어 페이지에서 상품을 크롤링한다.
Playwright로 JS 렌더링 후 DOM에서 상품 정보를 추출.

사용법:
    python -m scripts.crawl_coupang_brand
"""
import os
import re
import time
import uuid
from datetime import datetime
from typing import List, Dict, Any

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()           # .env (DB 설정 등)
load_dotenv("proxy.env")  # Bright Data 크리덴셜

import config
from scripts.crawl_naver import (
    save_to_db,
    analyze_product,
    NON_LIBRE_CGM_EXCLUDE_PATTERNS,
    load_confirmed_qty_by_link_map,
)

# 브랜드 스토어 목록
# - min_price: 이 금액 미만 상품 제외 (0이면 필터 없음)
# - name_filter: 상품명에 이 키워드가 포함된 것만 크롤링 (None이면 전체)
BRAND_STORES = [
    {
        "url": "https://shop.coupang.com/pillyze/?platform=p",
        "seller": "필라이즈",
        "min_price": 15000,
        "name_filter": None,
    },
    {
        "url": "https://shop.coupang.com/glucofit/?platform=p",
        "seller": "글루코핏",
        "min_price": 0,
        "name_filter": None,
    },
    {
        "url": "https://shop.coupang.com/A00158907/search?search=%EB%A6%AC%EB%B8%8C%EB%A0%882&platform=p",
        "seller": "닥터다이어리",
        "min_price": 0,
        "name_filter": r"리브레\s*2|libre\s*2",
    },
    {
        "url": "https://shop.coupang.com/promed/search?search=%EB%A6%AC%EB%B8%8C%EB%A0%882&platform=p",
        "seller": "하우투약",
        "min_price": 0,
        "name_filter": r"리브레\s*2|libre\s*2",
    },
    {
        "url": "https://shop.coupang.com/A00694926/search?search=%EB%A6%AC%EB%B8%8C%EB%A0%882&platform=p",
        "seller": "지씨",
        "min_price": 0,
        "name_filter": r"리브레\s*2|libre\s*2",
    },
    {
        "url": "https://shop.coupang.com/A01255118/search?search=%EB%A6%AC%EB%B8%8C%EB%A0%882&platform=p",
        "seller": "피플랜",
        "min_price": 0,
        "name_filter": r"리브레\s*2|libre\s*2",
    },
    {
        "url": "https://shop.coupang.com/A00306395/search?search=%EB%A6%AC%EB%B8%8C%EB%A0%882&platform=p",
        "seller": "좋은의료기",
        "min_price": 0,
        "name_filter": r"리브레\s*2|libre\s*2",
    },
    {
        "url": "https://shop.coupang.com/firstcare1004/search?search=%EB%A6%AC%EB%B8%8C%EB%A0%882&platform=p",
        "seller": "예성메디칼",
        "min_price": 0,
        "name_filter": r"리브레\s*2|libre\s*2",
    },
    {
        "url": "https://shop.coupang.com/A00214675/search?search=%EB%A6%AC%EB%B8%8C%EB%A0%882&platform=p",
        "seller": "가온씨엔티",
        "min_price": 0,
        "name_filter": r"리브레\s*2|libre\s*2",
    },
    {
        "url": "https://shop.coupang.com/A00206338/search?search=%EB%A6%AC%EB%B8%8C%EB%A0%882&platform=p",
        "seller": "네오클래스",
        "min_price": 0,
        "name_filter": r"리브레\s*2|libre\s*2",
    },
    {
        "url": "https://shop.coupang.com/storealpha/search?search=%EB%A6%AC%EB%B8%8C%EB%A0%882&platform=p",
        "seller": "알파플러스",
        "min_price": 0,
        "name_filter": r"리브레\s*2|libre\s*2",
    },
    {
        "url": "https://shop.coupang.com/A00309977/search?search=%EB%A6%AC%EB%B8%8C%EB%A0%882&platform=p",
        "seller": "건강생활",
        "min_price": 0,
        "name_filter": r"리브레\s*2|libre\s*2",
    },
    {
        "url": "https://shop.coupang.com/medicats/search?search=%EB%A6%AC%EB%B8%8C%EB%A0%882&platform=p",
        "seller": "메디캣",
        "min_price": 0,
        "name_filter": r"리브레\s*2|libre\s*2",
    },
    {
        "url": "https://shop.coupang.com/A00063576/search?search=%EB%A6%AC%EB%B8%8C%EB%A0%882&platform=p",
        "seller": "유니템아이",
        "min_price": 0,
        "name_filter": r"리브레\s*2|libre\s*2",
    },
    {
        "url": "https://shop.coupang.com/A00149074/search?search=%EB%A6%AC%EB%B8%8C%EB%A0%882&platform=p",
        "seller": "인터비즈",
        "min_price": 0,
        "name_filter": r"리브레\s*2|libre\s*2",
    },
    {
        "url": "https://shop.coupang.com/A00347924/search?search=%EB%A6%AC%EB%B8%8C%EB%A0%882&platform=p",
        "seller": "케이엔지",
        "min_price": 0,
        "name_filter": r"리브레\s*2|libre\s*2",
    },
    {
        "url": "https://shop.coupang.com/A01000648/search?search=%EB%A6%AC%EB%B8%8C%EB%A0%882&platform=p",
        "seller": "이지페어",
        "min_price": 0,
        "name_filter": r"리브레\s*2|libre\s*2",
    },
    {
        "url": "https://shop.coupang.com/A00186648/search?search=%EB%A6%AC%EB%B8%8C%EB%A0%882&platform=p",
        "seller": "메디칼의료기",
        "min_price": 0,
        "name_filter": r"리브레\s*2|libre\s*2",
    },
    {
        "url": "https://shop.coupang.com/A00568181/search?search=%EB%A6%AC%EB%B8%8C%EB%A0%882&platform=p",
        "seller": "씨엘메디",
        "min_price": 0,
        "name_filter": r"리브레\s*2|libre\s*2",
    },
    {
        "url": "https://shop.coupang.com/A01378801/search?search=%EB%A6%AC%EB%B8%8C%EB%A0%882&platform=p",
        "seller": "나눔메디",
        "min_price": 0,
        "name_filter": r"리브레\s*2|libre\s*2",
    },
    {
        "url": "https://shop.coupang.com/goodmorning67/search?search=%EB%A6%AC%EB%B8%8C%EB%A0%882&platform=p",
        "seller": "굿모닝의료기",
        "min_price": 0,
        "name_filter": r"리브레\s*2|libre\s*2",
    },
]

BRAND_KEYWORD = os.getenv("COUPANG_BRAND_KEYWORD", config.SEARCH_KEYWORD)

# Bright Data 주거용 프록시 설정
PROXY_SERVER = os.getenv("BRIGHT_DATA_PROXY")  # e.g. "http://brd.superproxy.io:22225"
PROXY_USERNAME = os.getenv("BRIGHT_DATA_USERNAME")
PROXY_PASSWORD = os.getenv("BRIGHT_DATA_PASSWORD")

# Bright Data Scraping Browser (원격 브라우저)
BROWSER_WSS = os.getenv("BRIGHT_DATA_BROWSER_WSS")  # e.g. "wss://...@brd.superproxy.io:9222"

# 브라우저 내에서 실행할 JS: 상품 링크에서 정보 추출
JS_EXTRACT = """() => {
    const links = document.querySelectorAll('a[href*="/products/"]');
    const results = [];
    const seen = new Set();

    for (const link of links) {
        const href = link.getAttribute('href') || '';
        const match = href.match(/products\\/(\\d+)/);
        if (!match) continue;
        const pid = match[1];

        const itemMatch = href.match(/itemId=(\\d+)/);
        const itemId = itemMatch ? itemMatch[1] : '';
        const key = pid + '_' + itemId;

        if (seen.has(key)) continue;
        seen.add(key);

        const text = link.innerText || '';
        const img = link.querySelector('img');
        const imgSrc = img ? (img.src || img.dataset.src || '') : '';
        const lines = text.split('\\n').map(l => l.trim()).filter(l => l.length > 0);

        // 가격 추출: "NNN,NNN원" 패턴
        const priceMatches = [...text.matchAll(/([\\d,]+)원/g)];
        const prices = priceMatches
            .map(m => parseInt(m[1].replace(/,/g, '')))
            .filter(p => p >= 1000 && p <= 2000000);

        results.push({
            pid: pid,
            itemId: itemId,
            href: href,
            lines: lines,
            imgSrc: imgSrc,
            prices: prices,
        });
    }
    return results;
}"""


def _pick_sale_price(prices: list, text: str) -> int:
    """가격 목록에서 판매가(실제 결제 금액)를 추출한다.

    쿠팡 브랜드 스토어 패턴:
    - "180,000원 (1개당 90,000원)"  → prices=[180000, 90000], 총액=180,000
    - "7% 194,000원 180,000원"     → prices=[194000, 180000], 할인가=180,000
    """
    if not prices:
        return 0
    if len(prices) == 1:
        return prices[0]

    # "N% " 할인율 표시가 있으면 → 할인 카드: 두 번째 가격이 판매가
    if re.search(r"\d+%", text):
        sorted_prices = sorted(prices, reverse=True)
        return sorted_prices[1] if len(sorted_prices) > 1 else sorted_prices[0]

    # "(1개당 N원)" 패턴이 있으면 → 총액 카드: 첫 번째(큰) 가격이 총액
    if "개당" in text:
        return max(prices)

    # 기본: 첫 번째 가격
    return prices[0]


def _extract_product_name(lines: list) -> str:
    """lines에서 상품명을 추출한다. line[0]은 셀러명, line[1]이 상품명."""
    if len(lines) >= 2:
        return lines[1]
    if lines:
        return lines[0]
    return ""


def _open_browser(p):
    """Playwright 인스턴스에서 브라우저 하나를 연다 (원격 또는 로컬)."""
    if BROWSER_WSS:
        print(f"[BRAND] Scraping Browser 사용 (원격)")
        last_err = None
        for attempt in range(1, 4):
            try:
                return p.chromium.connect_over_cdp(BROWSER_WSS, timeout=300000), "remote"
            except Exception as e:
                last_err = e
                wait = 10 * attempt
                print(f"  [RETRY {attempt}/3] WSS 연결 실패, {wait}s 대기 후 재시도: {e}")
                time.sleep(wait)
        raise RuntimeError(f"WSS 연결 최종 실패: {last_err}")

    # 로컬 브라우저
    launch_opts = {
        "headless": True,
        "args": [
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
        ],
    }
    if PROXY_SERVER:
        launch_opts["proxy"] = {
            "server": PROXY_SERVER,
            "username": PROXY_USERNAME,
            "password": PROXY_PASSWORD,
        }
        print(f"[BRAND] 프록시 사용: {PROXY_SERVER}")
    return p.chromium.launch(**launch_opts), "local"


def _new_page(browser, mode: str):
    """브라우저에서 새 페이지를 연다 (로컬은 stealth context 적용)."""
    if mode == "remote":
        return browser.new_page()
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1920, "height": 1080},
        locale="ko-KR",
        java_script_enabled=True,
        ignore_https_errors=True,
    )
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    """)
    return context.new_page()


def crawl_brand_store(browser, mode: str, url: str) -> List[Dict[str, Any]]:
    """브랜드 스토어 페이지를 크롤링한다 (브라우저는 호출자가 관리)."""
    print(f"[BRAND] 크롤링: {url}")
    page = _new_page(browser, mode)

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)

        # Access Denied 감지 시 재시도
        title = page.title()
        if "Access Denied" in title or "denied" in title.lower():
            print("  [RETRY] Access Denied 감지, 재시도...")
            page.wait_for_timeout(3000)
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(5000)

        # 점진적 스크롤로 lazy-load 상품 전부 로딩
        prev_count = 0
        for scroll_i in range(30):
            page.evaluate(f"window.scrollTo(0, {(scroll_i + 1) * 1000})")
            page.wait_for_timeout(800)
            cur_count = page.evaluate(
                "document.querySelectorAll('a[href*=\"/products/\"]').length"
            )
            if cur_count == prev_count and scroll_i > 3:
                break
            prev_count = cur_count

        title = page.title()
        print(f"  페이지: {title}")

        data = page.evaluate(JS_EXTRACT)
        print(f"  추출: {len(data)}개")

        if not data:
            print("  [WARN] 상품을 찾지 못했습니다.")
            os.makedirs("screenshots", exist_ok=True)
            ss = f"screenshots/brand_store_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            page.screenshot(path=ss, full_page=True)
            print(f"  스크린샷: {ss}")
            return []

        products = []
        for item in data:
            name = _extract_product_name(item["lines"])
            full_text = "\n".join(item["lines"])
            price = _pick_sale_price(item["prices"], full_text)
            href = item["href"]
            if not href.startswith("http"):
                href = f"https://www.coupang.com{href}"

            if not name or price <= 0:
                continue

            products.append({
                "product_name": name,
                "total_price": price,
                "link": href,
                "image_url": item["imgSrc"] or "",
            })

        return products

    except Exception as e:
        print(f"  [ERROR] 크롤링 실패: {e}")
        try:
            os.makedirs("screenshots", exist_ok=True)
            ss = f"screenshots/brand_error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            page.screenshot(path=ss, full_page=True)
            print(f"  에러 스크린샷: {ss}")
        except Exception:
            pass
        return []
    finally:
        try:
            page.close()
        except Exception:
            pass


def run_crawling():
    """메인 실행 함수."""
    print(f"START COUPANG BRAND STORE: {datetime.now().isoformat(timespec='seconds')}")

    confirmed_map = load_confirmed_qty_by_link_map()
    if confirmed_map:
        print(f"  수동확정 수량 재사용 맵: {len(confirmed_map)}개 링크")

    all_rows = []
    batch_size = 10

    with sync_playwright() as p:
        for batch_start in range(0, len(BRAND_STORES), batch_size):
            batch = BRAND_STORES[batch_start:batch_start + batch_size]
            batch_num = batch_start // batch_size + 1
            total_batches = (len(BRAND_STORES) + batch_size - 1) // batch_size

            if batch_start > 0:
                print(f"\n[BRAND] 브라우저 재연결 (IP 변경)... 15초 대기")
                time.sleep(15)

            print(f"\n[BATCH {batch_num}/{total_batches}] {len(batch)}개 스토어")
            browser, mode = _open_browser(p)

            try:
                for i, store in enumerate(batch):
                    url = store["url"]
                    seller = store["seller"]
                    min_price = store["min_price"]
                    name_filter = store.get("name_filter")

                    if i > 0:
                        time.sleep(8)

                    raw_products = crawl_brand_store(browser, mode, url)

                    if not raw_products:
                        print(f"  [{seller}] 크롤링된 상품 없음")
                        continue

                    kept = 0
                    skipped = 0
                    for prod in raw_products:
                        product_name = prod["product_name"]
                        total_price = prod["total_price"]

                        if name_filter and not re.search(name_filter, product_name, re.IGNORECASE):
                            skipped += 1
                            continue

                        if any(re.search(pat, product_name, re.IGNORECASE) for pat in NON_LIBRE_CGM_EXCLUDE_PATTERNS):
                            skipped += 1
                            print(f"  [SKIP] 비대상 CGM 제외: {product_name[:40]}")
                            continue

                        if re.search(r"바로잰", product_name, re.IGNORECASE):
                            skipped += 1
                            print(f"  [SKIP] 바로잰 제외: {product_name[:40]}")
                            continue

                        if min_price and total_price < min_price:
                            skipped += 1
                            print(f"  [SKIP] {product_name[:40]}  ({total_price:,} < {min_price:,})")
                            continue

                        qty, unit_price, how = analyze_product(
                            product_name,
                            total_price,
                            prod.get("link") or "",
                            confirmed_map,
                        )

                        row = {
                            "keyword": BRAND_KEYWORD,
                            "product_name": product_name,
                            "unit_price": unit_price,
                            "quantity": qty,
                            "total_price": total_price,
                            "mall_name": seller,
                            "calc_method": how,
                            "link": prod["link"],
                            "image_url": prod["image_url"],
                            "card_image_path": None,
                            "channel": "coupang",
                            "market": "쿠팡",
                        }
                        all_rows.append(row)
                        kept += 1

                        print(f"  [OK] {product_name[:50]}")
                        print(f"       total={total_price:,} qty={qty} unit={unit_price:,} ({how})")

                    filter_desc = []
                    if name_filter:
                        filter_desc.append(f"name='{name_filter}'")
                    if min_price:
                        filter_desc.append(f"min_price={min_price:,}")
                    filter_str = ", ".join(filter_desc) if filter_desc else "none"
                    print(f"  [{seller}] kept={kept}, skipped={skipped} (filter: {filter_str})")
                    print()
            finally:
                try:
                    browser.close()
                except Exception:
                    pass

    if not all_rows:
        print("[ERROR] 저장할 상품이 없습니다.")
        return

    # DB 저장 (전체 스토어 하나의 snapshot)
    snapshot_at = datetime.now().replace(microsecond=0)
    snapshot_id = f"{snapshot_at.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"

    inserted = save_to_db(all_rows, snapshot_id=snapshot_id, snapshot_at=snapshot_at)
    print(f"DB inserted: {inserted}")
    print(f"총 크롤링: {len(all_rows)}개, DB 저장: {inserted}개")
    print(f"END: {datetime.now().isoformat(timespec='seconds')}")


if __name__ == "__main__":
    run_crawling()
