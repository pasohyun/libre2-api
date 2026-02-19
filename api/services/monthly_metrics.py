from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session


def _month_range(month: str) -> Tuple[str, str]:
    """Return [start, end) as ISO dates for MySQL."""
    # month: 'YYYY-MM'
    y, m = month.split("-")
    y_i, m_i = int(y), int(m)
    if m_i == 12:
        end_y, end_m = y_i + 1, 1
    else:
        end_y, end_m = y_i, m_i + 1
    start = f"{y_i:04d}-{m_i:02d}-01 00:00:00"
    end = f"{end_y:04d}-{end_m:02d}-01 00:00:00"
    return start, end


def _snapshot_bucket(snapshot_id: Optional[str], snapshot_at: Optional[datetime], created_at: datetime) -> str:
    if snapshot_id:
        return snapshot_id
    ts = snapshot_at or created_at
    return ts.strftime("%Y-%m-%d %H")


def compute_monthly_seller_metrics(
    db: Session,
    *,
    month: str,
    threshold_price: int,
    channel: str = "naver",
) -> List[Dict[str, Any]]:
    """Compute seller metrics for a given month.

    Returns a list of dicts (ready for JSON + DB upsert).
    """
    start, end = _month_range(month)

    rows = db.execute(
        text(
            """
            SELECT
                mall_name,
                unit_price,
                link,
                calc_method,
                COALESCE(snapshot_at, created_at) AS ts,
                snapshot_id,
                snapshot_at,
                created_at,
                COALESCE(calc_valid, 1) AS calc_valid
            FROM products
            WHERE COALESCE(snapshot_at, created_at) >= :start
              AND COALESCE(snapshot_at, created_at) < :end
              AND channel = :channel
            """
        ),
        {"start": start, "end": end, "channel": channel},
    ).mappings().all()

    by_seller_bucket: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    calc_method_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for r in rows:
        seller = (r["mall_name"] or "").strip() or "(unknown)"
        ts = r["ts"]
        bucket = _snapshot_bucket(r.get("snapshot_id"), r.get("snapshot_at"), r.get("created_at"))
        calc_method_counts[seller][(r.get("calc_method") or "").strip()] += 1

        if int(r.get("calc_valid") or 1) != 1:
            continue

        cur = by_seller_bucket[seller].get(bucket)
        if (cur is None) or (r["unit_price"] < cur["unit_price"]):
            by_seller_bucket[seller][bucket] = {
                "unit_price": int(r["unit_price"]),
                "ts": ts,
                "link": r.get("link"),
            }

    results: List[Dict[str, Any]] = []

    for seller, bucket_map in by_seller_bucket.items():
        bucket_items = list(bucket_map.values())
        observations = len(bucket_items)
        if observations == 0:
            continue

        prices = sorted([x["unit_price"] for x in bucket_items])
        below_items = [x for x in bucket_items if x["unit_price"] <= threshold_price]
        below_cnt = len(below_items)
        below_ratio = below_cnt / observations if observations else 0.0

        min_item = min(bucket_items, key=lambda x: (x["unit_price"], x["ts"]))
        min_price = min_item["unit_price"]
        min_time = min_item["ts"]

        last_below_time = None
        last_below_item = None
        if below_items:
            last_below_item = max(below_items, key=lambda x: x["ts"])
            last_below_time = last_below_item["ts"]

        def _percentile(sorted_vals: List[int], p: float) -> float:
            if not sorted_vals:
                return 0.0
            k = (len(sorted_vals) - 1) * p
            f = int(k)
            c = min(f + 1, len(sorted_vals) - 1)
            if f == c:
                return float(sorted_vals[f])
            return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)

        p05 = _percentile(prices, 0.05)
        p95 = _percentile(prices, 0.95)
        volatility = float(p95 - p05)

        sorted_by_time = sorted(bucket_items, key=lambda x: x["ts"])
        sustained = 0
        cur_streak = 0
        dip_recover = 0
        prev_below = None
        for item in sorted_by_time:
            is_below = item["unit_price"] <= threshold_price
            if is_below:
                cur_streak += 1
            else:
                if cur_streak >= 2:
                    sustained += 1
                if prev_below is True:
                    dip_recover += 1
                cur_streak = 0
            prev_below = is_below
        if cur_streak >= 2:
            sustained += 1

        rep_links = {
            "min_case": min_item.get("link"),
            "last_below": (last_below_item or {}).get("link"),
        }

        results.append(
            {
                "month": month,
                "threshold_price": threshold_price,
                "channel": channel,
                "seller_name_std": seller,
                "observations": observations,
                "below_threshold_count": below_cnt,
                "below_ratio": round(below_ratio, 4),
                "min_unit_price": min_price,
                "min_time": min_time,
                "last_below_time": last_below_time,
                "volatility": round(volatility, 2),
                "representative_links": rep_links,
                "calc_method_stats": dict(calc_method_counts.get(seller, {})),
                "dip_recover_count": dip_recover,
                "sustained_below_count": sustained,
                "cross_platform_mismatch": None,
            }
        )

    results.sort(key=lambda x: (-x["below_threshold_count"], x["min_unit_price"]))
    return results


def upsert_monthly_metrics(db: Session, metrics: List[Dict[str, Any]]) -> int:
    if not metrics:
        return 0

    sql = text(
        """
        INSERT INTO monthly_seller_metrics (
            month, threshold_price, channel, seller_name_std,
            observations, below_threshold_count, below_ratio,
            min_unit_price, min_time, last_below_time,
            volatility, representative_links, calc_method_stats,
            dip_recover_count, sustained_below_count, cross_platform_mismatch
        ) VALUES (
            :month, :threshold_price, :channel, :seller_name_std,
            :observations, :below_threshold_count, :below_ratio,
            :min_unit_price, :min_time, :last_below_time,
            :volatility, :representative_links, :calc_method_stats,
            :dip_recover_count, :sustained_below_count, :cross_platform_mismatch
        )
        ON DUPLICATE KEY UPDATE
            observations=VALUES(observations),
            below_threshold_count=VALUES(below_threshold_count),
            below_ratio=VALUES(below_ratio),
            min_unit_price=VALUES(min_unit_price),
            min_time=VALUES(min_time),
            last_below_time=VALUES(last_below_time),
            volatility=VALUES(volatility),
            representative_links=VALUES(representative_links),
            calc_method_stats=VALUES(calc_method_stats),
            dip_recover_count=VALUES(dip_recover_count),
            sustained_below_count=VALUES(sustained_below_count),
            cross_platform_mismatch=VALUES(cross_platform_mismatch)
        """
    )

    params = []
    for m in metrics:
        params.append(
            {
                **m,
                "representative_links": json.dumps(m.get("representative_links"), ensure_ascii=False),
                "calc_method_stats": json.dumps(m.get("calc_method_stats"), ensure_ascii=False),
            }
        )

    db.execute(sql, params)
    db.commit()
    return len(metrics)


def load_monthly_metrics(db: Session, *, month: str, threshold_price: int, channel: str) -> List[Dict[str, Any]]:
    rows = db.execute(
        text(
            """
            SELECT
                month, threshold_price, channel, seller_name_std,
                observations, below_threshold_count, below_ratio,
                min_unit_price, min_time, last_below_time,
                volatility, representative_links, calc_method_stats,
                dip_recover_count, sustained_below_count, cross_platform_mismatch
            FROM monthly_seller_metrics
            WHERE month=:month AND threshold_price=:threshold_price AND channel=:channel
            ORDER BY below_threshold_count DESC, min_unit_price ASC
            """
        ),
        {"month": month, "threshold_price": threshold_price, "channel": channel},
    ).mappings().all()

    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        for k in ("representative_links", "calc_method_stats"):
            v = d.get(k)
            if isinstance(v, str):
                try:
                    d[k] = json.loads(v)
                except Exception:
                    d[k] = None
        out.append(d)
    return out
