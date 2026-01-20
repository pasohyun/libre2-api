import os
import uuid
import asyncio
from dataclasses import dataclass
from typing import List

import requests
from playwright.async_api import async_playwright

# ==========================================
# 1. API 키 설정 (crawl_naver.py와 동일하게 사용)
# ==========================================
CLIENT_ID = "NXeGJZXkxK8ZyE4l4bsR"
CLIENT_SECRET = "9c5ZGASXBK"

# ==========================================
# 2. 상품 데이터 모델
# ==========================================
@dataclass
class Product:
    platform: str
    name: str
    price: int
    url: str
    image_url: str | None = None
    mall_name: str | None = None

# ==========================================
# 3. 네이버 API로 상품 데이터 가져오기 (간단 예시)
# ==========================================
def fetch_products_via_naver_api(query: str = "프리스타일 리브레2", display: int = 10) -> List[Product]:
    enc_query = requests.utils.quote(query)
    url = f"https://openapi.naver.com/v1/search/shop.json?query={enc_query}&display={display}&start=1&sort=sim"
    headers = {
        "X-Naver-Client-Id": CLIENT_ID,
        "X-Naver-Client-Secret": CLIENT_SECRET,
    }
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    products: List[Product] = []
    for item in data.get("items", []):
        raw_title = item.get("title", "")
        clean_title = raw_title.replace("<b>", "").replace("</b>", "").strip()
        try:
            price = int(item.get("lprice", "0"))
        except ValueError:
            price = 0

        products.append(
            Product(
                platform="naver",
                name=clean_title or raw_title,
                price=price,
                url=item.get("link", ""),
                image_url=item.get("image"),
                mall_name=item.get("mallName"),
            )
        )
    return products

# ==========================================
# 4. HTML 카드 템플릿 생성
# ==========================================
def build_product_card_html(product: Product) -> str:
    return f"""
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <title>{product.name}</title>
  <style>
    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen,
                   Ubuntu, Cantarell, "Helvetica Neue", sans-serif;
    }}
    body {{
      width: 800px;
      height: 450px;
      background: linear-gradient(135deg, #f4f7fb 0%, #e8f0ff 100%);
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .card {{
      width: 720px;
      padding: 24px 28px;
      background: #ffffff;
      border-radius: 16px;
      box-shadow: 0 18px 45px rgba(15, 23, 42, 0.12);
      display: flex;
      gap: 20px;
    }}
    .thumb {{
      flex: 0 0 180px;
      height: 180px;
      border-radius: 12px;
      background: #f3f4f6;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
      position: relative;
    }}
    .thumb::after {{
      content: "NAVER";
      position: absolute;
      bottom: 10px;
      right: 12px;
      font-size: 11px;
      padding: 2px 6px;
      border-radius: 999px;
      background: rgba(16, 185, 129, 0.9);
      color: #fff;
      font-weight: 600;
      letter-spacing: 0.03em;
    }}
    .thumb img {{
      max-width: 100%;
      max-height: 100%;
      object-fit: contain;
    }}
    .thumb-placeholder {{
      font-size: 14px;
      color: #9ca3af;
    }}
    .content {{
      flex: 1;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }}
    .title {{
      font-size: 18px;
      font-weight: 600;
      color: #111827;
      line-height: 1.4;
      margin-bottom: 8px;
    }}
    .meta {{
      font-size: 13px;
      color: #6b7280;
      margin-bottom: 16px;
    }}
    .price {{
      font-size: 24px;
      font-weight: 700;
      color: #111827;
      margin-bottom: 6px;
    }}
    .price span.unit {{
      font-size: 14px;
      font-weight: 500;
      color: #6b7280;
      margin-left: 4px;
    }}
    .footer {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-top: 12px;
    }}
    .badge {{
      font-size: 11px;
      padding: 4px 10px;
      border-radius: 999px;
      background: #ecfdf5;
      color: #047857;
      font-weight: 600;
      letter-spacing: 0.02em;
    }}
    .link-btn {{
      font-size: 13px;
      font-weight: 600;
      padding: 8px 16px;
      border-radius: 999px;
      border: none;
      background: #2563eb;
      color: #ffffff;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }}
    .link-btn span.arrow {{
      font-size: 14px;
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="thumb">
      {"<img src='" + product.image_url + "' alt='상품 이미지' />" if product.image_url else "<div class='thumb-placeholder'>이미지 없음</div>"}
    </div>
    <div class="content">
      <div>
        <div class="title">{product.name}</div>
        <div class="meta">{product.platform.upper()}{" · " + product.mall_name if product.mall_name else ""} · 자동 생성 카드</div>
        <div class="price">
          {product.price:,.0f}<span class="unit">원</span>
        </div>
      </div>
      <div class="footer">
        <div class="badge">NAVER DATA · INTERNAL USE</div>
        <a class="link-btn" href="{product.url}" target="_blank" rel="noreferrer">
          네이버에서 보기
          <span class="arrow">↗</span>
        </a>
      </div>
    </div>
  </div>
</body>
</html>
"""

# ==========================================
# 5. Playwright로 HTML을 열어 스크린샷 찍기
# ==========================================
async def render_card_to_png(product: Product, out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)

    # 1) HTML 저장
    html = build_product_card_html(product)
    html_filename = f"{uuid.uuid4()}.html"
    html_path = os.path.join(out_dir, html_filename)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    # 2) 스크린샷
    png_filename = f"{uuid.uuid4()}.png"
    png_path = os.path.join(out_dir, png_filename)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 800, "height": 450})
        await page.goto(f"file:///{os.path.abspath(html_path)}")
        await page.wait_for_timeout(1000)
        await page.screenshot(path=png_path, full_page=False)
        await browser.close()
    return png_path

# ==========================================
# 6. 단독 실행시: API 데이터로 카드 생성 데모
# ==========================================
async def main():
    print("[NAVER] 공식 API 데이터 기반 카드 이미지 생성 시작…")
    products = fetch_products_via_naver_api()
    if not products:
        print("상품 데이터가 없습니다. 네이버 API 코드가 제대로 동작하는지 확인하세요.")
        return

    output_dir = "product_cards"
    results = []
    for p in products:
        try:
            png_path = await render_card_to_png(p, output_dir)
            results.append({"name": p.name, "price": p.price, "url": p.url, "card_image_path": png_path})
            print(f"[OK] {p.name} -> {png_path}")
        except Exception as e:
            print(f"[ERROR] {p.name}: {e}")

    print(f"\n총 {len(results)}개 상품 카드 이미지를 생성했습니다.")
    return results

if __name__ == "__main__":
    asyncio.run(main())
