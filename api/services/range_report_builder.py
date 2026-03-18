from __future__ import annotations

import html as _html
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from api.services.range_metrics import (
    compute_below_threshold_detail,
    compute_seller_chart_data,
    compute_seller_metrics,
)


def _safe(value: object) -> str:
    return _html.escape(str(value or ""))


def _build_evidence_card_html(item: Dict[str, Any]) -> str:
    """Build the same evidence-card HTML as card_renderer._build_card_html."""
    title = _safe(item.get("product_name"))
    mall_name = _safe(item.get("seller_name"))
    link = _safe(item.get("link"))
    image_url = _safe(item.get("image_url"))
    unit_price = int(item.get("unit_price") or 0)
    total_price = int(item.get("total_price") or 0)
    quantity = int(item.get("quantity") or 0)
    calc_method = _safe(item.get("calc_method"))

    captured_at = item.get("time") or datetime.now()
    if isinstance(captured_at, str):
        try:
            captured_at = datetime.fromisoformat(captured_at)
        except ValueError:
            captured_at = datetime.now()
    captured_at_str = captured_at.strftime("%Y-%m-%d %H:%M:%S KST")

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; width: 1000px; height: 560px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: linear-gradient(120deg, #eef2ff 0%, #f8fafc 100%);
      color: #0f172a; display: flex; align-items: center; justify-content: center;
    }}
    .card {{
      width: 940px; height: 500px; border-radius: 20px; background: #fff;
      box-shadow: 0 20px 45px rgba(2,6,23,0.12); padding: 24px;
      display: grid; grid-template-columns: 320px 1fr; gap: 22px;
    }}
    .left {{
      border: 1px solid #e2e8f0; border-radius: 14px; overflow: hidden;
      display: flex; align-items: center; justify-content: center;
      background: #f8fafc; position: relative;
    }}
    .left img {{ max-width: 100%; max-height: 100%; object-fit: contain; }}
    .badge {{
      position: absolute; top: 10px; left: 10px; background: #2563eb; color: #fff;
      font-size: 12px; font-weight: 700; border-radius: 999px; padding: 4px 10px;
    }}
    .right {{ display: flex; flex-direction: column; justify-content: space-between; }}
    .title {{
      font-size: 34px; line-height: 1.25; font-weight: 800;
      margin-bottom: 12px; max-height: 130px; overflow: hidden;
    }}
    .sub {{ color: #475569; font-size: 16px; margin-bottom: 14px; }}
    .price {{ display: flex; align-items: baseline; gap: 8px; margin: 6px 0 14px 0; }}
    .price .main {{ font-size: 56px; font-weight: 900; color: #111827; }}
    .price .unit {{ font-size: 30px; color: #6b7280; font-weight: 700; }}
    .grid {{
      display: grid; grid-template-columns: 160px 1fr;
      row-gap: 8px; column-gap: 10px; font-size: 18px;
    }}
    .k {{ color: #64748b; font-weight: 700; }}
    .v {{ color: #0f172a; font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .footer {{
      margin-top: 16px; border-top: 1px solid #e2e8f0; padding-top: 12px;
      display: flex; justify-content: space-between; align-items: center;
      color: #334155; font-size: 14px; gap: 10px;
    }}
    .url {{ max-width: 560px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
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
</html>"""


def build_range_report(
    db: Session,
    *,
    start_date: str,
    end_date: str,
    threshold_price: int,
    channel: str = "naver",
) -> Dict[str, Any]:
    # ── Section 1: Summary ──────────────────────────────────────────
    summary = compute_seller_metrics(
        db,
        start_date=start_date,
        end_date=end_date,
        threshold_price=threshold_price,
        channel=channel,
    )

    # ── Section 2: Below-threshold detail list ──────────────────────
    below_list = compute_below_threshold_detail(
        db,
        start_date=start_date,
        end_date=end_date,
        threshold_price=threshold_price,
        channel=channel,
    )

    # Attach card_html to seller-level min + each snapshot
    for item in below_list:
        item["card_html"] = _build_evidence_card_html(item)
        for snap in item.get("snapshots") or []:
            snap["card_html"] = _build_evidence_card_html(snap)

    # ── Section 3: Seller chart data ────────────────────────────────
    seller_names = [item["seller_name"] for item in below_list]
    chart_data = compute_seller_chart_data(
        db,
        start_date=start_date,
        end_date=end_date,
        seller_names=seller_names or None,
        channel=channel,
    )

    # Assemble seller detail cards
    seller_cards: List[Dict[str, Any]] = []
    for item in below_list:
        name = item["seller_name"]
        seller_cards.append({
            "seller_name": name,
            "platform": item["platform"],
            "min_unit_price": item["unit_price"],
            "min_time": item["time"],
            "total_price": item["total_price"],
            "quantity": item["quantity"],
            "link": item.get("link"),
            "card_image_path": item.get("card_image_path"),
            "chart_data": chart_data.get(name, []),
        })

    return {
        "start_date": start_date,
        "end_date": end_date,
        "threshold_price": threshold_price,
        "channel": channel,
        "summary": summary,
        "below_threshold_list": below_list,
        "seller_cards": seller_cards,
        "generated_at": datetime.now(),
    }


def render_range_markdown(report: Dict[str, Any]) -> str:
    sd = report["start_date"]
    ed = report["end_date"]
    thr = report["threshold_price"]
    ch = report["channel"]
    summary = report.get("summary") or {}

    lines: List[str] = []
    lines.append(f"# Libre2 Date-Range Report ({sd} ~ {ed})")
    lines.append("")
    lines.append(f"- Channel: **{ch}**")
    lines.append(f"- Threshold: **{thr:,}원**")
    lines.append(f"- Generated at: {report.get('generated_at')}")
    lines.append("")

    # ── Section 1: Summary ──────────────────────────────────────────
    lines.append("## ① Summary")
    lines.append(f"- 기준가 이하 셀러 수: **{summary.get('below_threshold_seller_count', 0)}곳**")

    top5 = summary.get("top5_lowest") or []
    if top5:
        lines.append("- 거래처명 (최저가격 상위 5처):")
        for s in top5:
            lines.append(f"  - {s['seller_name']}: {s['min_unit_price']:,}원")

    if summary.get("global_min_price"):
        lines.append(
            f"- 최저 단가: **{summary['global_min_price']:,}원** "
            f"({summary.get('global_min_seller')}) @ {summary.get('global_min_time')}"
        )
    lines.append("")

    # ── Section 2: Below-threshold list ─────────────────────────────
    below = report.get("below_threshold_list") or []
    lines.append("## ② 기준가 이하 리스트")
    if below:
        lines.append("| 셀러명 | 플랫폼 | 최저 단가(시점) | 금액 | 수량 | 카드 |")
        lines.append("|---|---|---|---:|---:|---|")
        for item in below:
            card = item.get("card_image_path") or ""
            lines.append(
                f"| {item['seller_name']} "
                f"| {item['platform']} "
                f"| {item['unit_price']:,}원 ({item['time']}) "
                f"| {item['total_price']:,}원 "
                f"| {item['quantity']} "
                f"| {card} |"
            )
    else:
        lines.append("기준가 이하 셀러가 없습니다.")
    lines.append("")

    # ── Section 3: Seller detail cards ──────────────────────────────
    cards = report.get("seller_cards") or []
    lines.append("## ③ 셀러별 상세 카드")
    for card in cards:
        lines.append(f"### {card['seller_name']} ({card['platform']})")
        lines.append(f"- 최저 단가: {card['min_unit_price']:,}원 @ {card['min_time']}")
        chart = card.get("chart_data") or []
        if chart:
            lines.append(f"- 최저가 시계열 ({len(chart)}건):")
            for pt in chart:
                lines.append(f"  - {pt['date']} {pt.get('time', '')}: {pt['min_price']:,}원")
        lines.append("")

    return "\n".join(lines)
