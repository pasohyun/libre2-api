from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from api.services.monthly_metrics import compute_monthly_seller_metrics, upsert_monthly_metrics


def build_monthly_report(
    db: Session,
    *,
    month: str,
    threshold_price: int,
    channel: str = "naver",
    crawl_schedule: str = "00/12",
    platforms: Optional[List[str]] = None,
    top_cards: int = 10,
    use_llm: bool = True,  # 지금은 사용 안 함 (서버 안정용)
    store: bool = False,
) -> Dict[str, Any]:
    platforms = platforms or [channel]

    # 1) 월간 집계(숫자는 DB 기반으로 확정)
    metrics = compute_monthly_seller_metrics(
        db,
        month=month,
        threshold_price=threshold_price,
        channel=channel,
    )

    if store:
        upsert_monthly_metrics(db, metrics)

    # 2) 기준가 이하 seller만 우선순위 리스트 구성
    priority_list = []
    for m in metrics:
        if (m.get("below_threshold_count") or 0) <= 0:
            continue

        priority_list.append(
            {
                "seller_name_std": m["seller_name_std"],
                "platform": channel,
                "below_threshold_count": m["below_threshold_count"],
                "observations": m["observations"],
                "below_ratio": m["below_ratio"],
                "min_unit_price": m["min_unit_price"],
                "min_time": m["min_time"],
                "last_below_time": m["last_below_time"],
                "representative_link": (m.get("representative_links") or {}).get("min_case"),
            }
        )

    has_below = len(priority_list) > 0

    # 최저 단가/시점 (전역)
    min_global = None
    for m in priority_list:
        if min_global is None or (m["min_unit_price"] is not None and m["min_unit_price"] < min_global["min_unit_price"]):
            min_global = m

    conclusion = {
        "has_below_threshold_seller": has_below,
        "problem_seller_count": len(priority_list),
        "global_min_unit_price": (min_global or {}).get("min_unit_price"),
        "global_min_time": (min_global or {}).get("min_time"),
        "repeat_pattern_observed": any((x.get("sustained_below_count") or 0) > 0 for x in metrics),
    }

    # 3) 셀러 카드 (top N)
    seller_cards = []
    for item in priority_list[: max(0, top_cards)]:
        seller = item["seller_name_std"]
        mm = next((x for x in metrics if x["seller_name_std"] == seller), None) or {}

        seller_cards.append(
            {
                "seller_name_std": seller,
                "platform": item["platform"],
                "platform_price_summary": {
                    "status": "변동" if (item.get("below_ratio", 0) > 0) else "안정",
                    "volatility": mm.get("volatility"),
                },
                "representative_cases": [
                    {
                        "unit_price": item["min_unit_price"],
                        "time": item["min_time"],
                        "link": item.get("representative_link"),
                    }
                ],
                "recommendation": None,  # LLM 붙일 때 여기에 문장 넣으면 됨
                "evidence_links": {
                    "min_case": item.get("representative_link"),
                },
            }
        )

    # 4) 관측 기반 패턴
    patterns = []
    dip_sellers = [m["seller_name_std"] for m in metrics if (m.get("dip_recover_count") or 0) > 0]
    if dip_sellers:
        patterns.append(
            {
                "title": "하락 후 복귀(dip→recover) 패턴",
                "description": "관측된 범위 내에서, 기준가 이하로 하락했다가 이후 다시 복귀한 이력이 있는 셀러가 존재합니다.",
                "evidence_sellers": dip_sellers[:10],
                "caution": "관측된 범위 내에서의 패턴이며, 확정적 원인은 아닙니다.",
            }
        )

    sustained_sellers = [m["seller_name_std"] for m in metrics if (m.get("sustained_below_count") or 0) > 0]
    if sustained_sellers:
        patterns.append(
            {
                "title": "지속 이탈(sustained below) 패턴",
                "description": "관측된 범위 내에서, 기준가 이하 상태가 연속 구간으로 이어진 셀러가 있습니다.",
                "evidence_sellers": sustained_sellers[:10],
                "caution": "관측된 범위 내에서의 패턴이며, 확정적 원인은 아닙니다.",
            }
        )

    # 5) 데이터 품질
    total_rows = sum(sum((m.get("calc_method_stats") or {}).values()) for m in metrics)
    unclear_rows = 0
    for m in metrics:
        for k, v in (m.get("calc_method_stats") or {}).items():
            if "확인" in (k or "") or "범위초과" in (k or ""):
                unclear_rows += int(v)

    unclear_ratio = (unclear_rows / total_rows) if total_rows else 0.0

    data_quality = {
        "unclear_calc_ratio": round(unclear_ratio, 4),
        "notes": [
            "단가 계산 로직은 제목 기반 텍스트 분석 + (필요 시) 가격 역산 보정으로 구성되어 있습니다.",
            "'확인필요' 또는 '범위초과' 표기는 자동 단가가 신뢰되지 않을 수 있음을 의미합니다.",
        ],
        "next_month_improvements": [
            "snapshot_id/snapshot_at를 크롤러에 항상 기록해 관측 단위를 고정하기",
            "사은품/세트 표기 패턴을 추가 반영해 '확인필요' 비율 낮추기",
            "(쿠팡 추가 후) 플랫폼 간 동시 이탈/불일치 규칙 고도화하기",
        ],
    }

    report = {
        "month": month,
        "threshold_price": threshold_price,
        "channel": channel,
        "conclusion": conclusion,
        "priority_list": priority_list,
        "seller_cards": seller_cards,
        "patterns": patterns,
        "data_quality": data_quality,
        "llm": None,  # MVP에서는 비움
        "generated_at": datetime.now(),
    }

    return report


def render_markdown(report: Dict[str, Any]) -> str:
    m = report["month"]
    thr = report["threshold_price"]
    ch = report["channel"]

    lines = []
    lines.append(f"# Libre2 Monthly Price Report ({m})")
    lines.append("")
    lines.append(f"- Channel: **{ch}**")
    lines.append(f"- Threshold: **{thr:,}원**")
    lines.append(f"- Generated at: {report.get('generated_at')}")
    lines.append("")

    c = report.get("conclusion") or {}
    lines.append("## ① 이번 달 결론 요약")
    lines.append(f"- 기준가 이하 셀러: **{'있음' if c.get('has_below_threshold_seller') else '없음'}**")
    lines.append(f"- 문제 셀러: **{c.get('problem_seller_count', 0)}곳**")
    if c.get("global_min_unit_price"):
        lines.append(f"- 최저 단가/시점: **{int(c['global_min_unit_price']):,}원** @ {c.get('global_min_time')}")
    lines.append(f"- 반복 패턴 여부(관측 범위 내): **{'있음' if c.get('repeat_pattern_observed') else '없음'}**")
    lines.append("")

    lines.append("## ② 기준가 이하 셀러 우선순위 리스트")
    lines.append("| seller | platform | below/obs | min (time) | last below | link |")
    lines.append("|---|---|---:|---|---|---|")
    for item in report.get("priority_list") or []:
        seller = item.get("seller_name_std")
        platform = item.get("platform")
        below = item.get("below_threshold_count")
        obs = item.get("observations")
        min_price = item.get("min_unit_price") or 0
        min_time = item.get("min_time")
        last_below = item.get("last_below_time")
        link = item.get("representative_link") or ""
        lines.append(f"| {seller} | {platform} | {below}/{obs} | {min_price:,} ({min_time}) | {last_below} | {link} |")
    lines.append("")

    lines.append("## ③ 셀러별 상세 카드")
    for card in report.get("seller_cards") or []:
        lines.append(f"### {card.get('seller_name_std')} ({card.get('platform')})")
        ps = card.get("platform_price_summary") or {}
        lines.append(f"- 플랫폼 요약: {ps.get('status')} / volatility={ps.get('volatility')}")
        for case in card.get("representative_cases") or []:
            lines.append(f"- 사례: {case.get('unit_price'):,}원 @ {case.get('time')} / {case.get('link')}")
        lines.append("")

    lines.append("## ④ 패턴 요약 (관측 기반)")
    for p in report.get("patterns") or []:
        lines.append(f"- **{p.get('title')}**: {p.get('description')}")
        if p.get("evidence_sellers"):
            lines.append(f"  - evidence_sellers: {', '.join(p['evidence_sellers'])}")
        lines.append(f"  - ⚠️ {p.get('caution')}")
    lines.append("")

    dq = report.get("data_quality") or {}
    lines.append("## ⑤ 데이터 품질 / 주의 사항")
    lines.append(f"- 단가 계산 확인필요 비율: **{float(dq.get('unclear_calc_ratio') or 0)*100:.2f}%**")
    for n in dq.get("notes") or []:
        lines.append(f"- {n}")
    lines.append("")
    lines.append("### 다음 달 보완 포인트")
    for n in dq.get("next_month_improvements") or []:
        lines.append(f"- {n}")

    return "\n".join(lines)
