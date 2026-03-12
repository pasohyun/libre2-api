from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from api.services.range_metrics import (
    compute_below_threshold_detail,
    compute_seller_chart_data,
    compute_seller_metrics,
)


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
            lines.append(f"- 일별 최저가 데이터 ({len(chart)}일):")
            for pt in chart:
                lines.append(f"  - {pt['date']}: {pt['min_price']:,}원")
        lines.append("")

    return "\n".join(lines)
