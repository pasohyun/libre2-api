from __future__ import annotations

import asyncio
import html
import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright


def _safe_text(value: object) -> str:
    return html.escape(str(value or ""))


def _build_card_html(product: dict, captured_at: datetime) -> str:
    title = _safe_text(product.get("product_name"))
    mall_name = _safe_text(product.get("mall_name"))
    link = _safe_text(product.get("link"))
    image_url = _safe_text(product.get("image_url"))

    unit_price = int(product.get("unit_price") or 0)
    total_price = int(product.get("total_price") or 0)
    quantity = int(product.get("quantity") or 0)
    calc_method = _safe_text(product.get("calc_method"))

    captured_at_str = captured_at.strftime("%Y-%m-%d %H:%M:%S KST")

    return f"""
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Price Evidence Card</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      width: 1000px;
      height: 560px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: linear-gradient(120deg, #eef2ff 0%, #f8fafc 100%);
      color: #0f172a;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .card {{
      width: 940px;
      height: 500px;
      border-radius: 20px;
      background: #fff;
      box-shadow: 0 20px 45px rgba(2, 6, 23, 0.12);
      padding: 24px;
      display: grid;
      grid-template-columns: 320px 1fr;
      gap: 22px;
    }}
    .left {{
      border: 1px solid #e2e8f0;
      border-radius: 14px;
      overflow: hidden;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #f8fafc;
      position: relative;
    }}
    .left img {{
      max-width: 100%;
      max-height: 100%;
      object-fit: contain;
    }}
    .badge {{
      position: absolute;
      top: 10px;
      left: 10px;
      background: #2563eb;
      color: #fff;
      font-size: 12px;
      font-weight: 700;
      border-radius: 999px;
      padding: 4px 10px;
    }}
    .right {{
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }}
    .title {{
      font-size: 34px;
      line-height: 1.25;
      font-weight: 800;
      margin-bottom: 12px;
      max-height: 130px;
      overflow: hidden;
    }}
    .sub {{
      color: #475569;
      font-size: 16px;
      margin-bottom: 14px;
    }}
    .price {{
      display: flex;
      align-items: baseline;
      gap: 8px;
      margin: 6px 0 14px 0;
    }}
    .price .main {{
      font-size: 56px;
      font-weight: 900;
      color: #111827;
    }}
    .price .unit {{
      font-size: 30px;
      color: #6b7280;
      font-weight: 700;
    }}
    .grid {{
      display: grid;
      grid-template-columns: 160px 1fr;
      row-gap: 8px;
      column-gap: 10px;
      font-size: 18px;
    }}
    .k {{ color: #64748b; font-weight: 700; }}
    .v {{ color: #0f172a; font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .footer {{
      margin-top: 16px;
      border-top: 1px solid #e2e8f0;
      padding-top: 12px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      color: #334155;
      font-size: 14px;
      gap: 10px;
    }}
    .url {{
      max-width: 560px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="left">
      <div class="badge">EVIDENCE</div>
      <img src="{image_url}" alt="product image" />
    </div>
    <div class="right">
      <div>
        <div class="title">{title}</div>
        <div class="sub">판매처: {mall_name}</div>
        <div class="price">
          <div class="main">{unit_price:,}</div>
          <div class="unit">원/개</div>
        </div>
        <div class="grid">
          <div class="k">총 가격</div><div class="v">{total_price:,}원</div>
          <div class="k">수량</div><div class="v">{quantity}개</div>
          <div class="k">계산 방식</div><div class="v">{calc_method}</div>
          <div class="k">생성 시각</div><div class="v">{captured_at_str}</div>
        </div>
      </div>
      <div class="footer">
        <div>NAVER PRICE EVIDENCE CARD</div>
        <div class="url">{link}</div>
      </div>
    </div>
  </div>
</body>
</html>
"""


async def _render_card_png_async(*, html_text: str, out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    out_path = str(Path(out_dir) / f"{uuid.uuid4()}.png")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1000, "height": 560})
        await page.set_content(html_text, wait_until="networkidle")
        await page.screenshot(path=out_path, full_page=False)
        await browser.close()

    return out_path


def _install_playwright_chromium() -> None:
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def render_card_png(*, product: dict, out_dir: str, captured_at: datetime) -> str:
    html_text = _build_card_html(product, captured_at)
    try:
        return asyncio.run(_render_card_png_async(html_text=html_text, out_dir=out_dir))
    except Exception as first_error:
        # In some environments Chromium is missing on first deploy; install once and retry.
        _install_playwright_chromium()
        try:
            return asyncio.run(_render_card_png_async(html_text=html_text, out_dir=out_dir))
        except Exception:
            raise first_error
