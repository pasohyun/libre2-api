# scripts/crawl_coupang_brand.py
"""
쿠팡 브랜드 스토어 페이지에서 상품을 크롤링한다.
Playwright로 JS 렌더링 후 DOM에서 상품 정보를 추출.

사용법:
    python -m scripts.crawl_coupang_brand
"""
import os
import re
import uuid
from datetime import datetime
from typing import List, Dict, Any

from playwright.sync_api import sync_playwright

import config
from scripts.crawl_naver import save_to_db, analyze_product

# 브랜드 스토어 목록
# - min_price: 이 금액 미만 상품 제외 (0이면 필터 없음)
# - name_filter: 상품명에 이 키워드가 포함된 것만 크롤링 (None이면 전체)
BRAND_STORES = [
    {
        "url": "https://shop.coupang.com/glucofit/339397",
        "seller": "글루코핏",
        "min_price": 0,
        "name_filter": None,
    },
    {
        "url": "https://shop.coupang.com/pillyze/?platform=p",
        "seller": "필라이즈",
        "min_price": 15000,
        "name_filter": None,
    },
    {
        "url": "https://shop.coupang.com/A00158907/?platform=p",
        "seller": "닥터다이어리",
        "min_price": 0,
        "name_filter": r"리브레\s*2|libre\s*2",
    },
]

BRAND_KEYWORD = os.getenv("COUPANG_BRAND_KEYWORD", config.SEARCH_KEYWORD)

# 브라우저 내에서 실행할 JS: 상품 링크에서 정보 추출
JS_EXTRACT = """() => {
    const links = document.querySelectorAll('a[href*="/products/"]');
    const results = [];
    const seen = new Set();

    for (const link of links) {
        const href = link.getAttribute('href') || '';
        const match = href.match(/products\/(\d+)/);
        if (!match) continue;
        const pid = match[1];

        const itemMatch = href.match(/itemId=(\d+)/);
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


def crawl_brand_store(url: str) -> List[Dict[str, Any]]:
    """브랜드 스토어 페이지를 Playwright로 크롤링한다."""
    print(f"[BRAND] 크롤링: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="ko-KR",
        )
        page = context.new_page()

        try:
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
            browser.close()


def run_crawling():
    """메인 실행 함수."""
    print(f"START COUPANG BRAND STORE: {datetime.now().isoformat(timespec='seconds')}")

    all_rows = []

    for store in BRAND_STORES:
        url = store["url"]
        seller = store["seller"]
        min_price = store["min_price"]
        name_filter = store.get("name_filter")

        raw_products = crawl_brand_store(url)

        if not raw_products:
            print(f"  [{seller}] 크롤링된 상품 없음")
            continue

        kept = 0
        skipped = 0
        for p in raw_products:
            product_name = p["product_name"]
            total_price = p["total_price"]

            # 상품명 필터 (정규식, 대소문자 무시)
            if name_filter and not re.search(name_filter, product_name, re.IGNORECASE):
                skipped += 1
                continue

            # 최소 가격 필터
            if min_price and total_price < min_price:
                skipped += 1
                print(f"  [SKIP] {product_name[:40]}  ({total_price:,} < {min_price:,})")
                continue

            qty, unit_price, how = analyze_product(product_name, total_price)

            row = {
                "keyword": BRAND_KEYWORD,
                "product_name": product_name,
                "unit_price": unit_price,
                "quantity": qty,
                "total_price": total_price,
                "mall_name": seller,
                "calc_method": how,
                "link": p["link"],
                "image_url": p["image_url"],
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
