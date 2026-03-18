from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session


def _date_range(start_date: str, end_date: str) -> Tuple[str, str]:
    """Return [start, end) timestamps. end_date is inclusive (up to 23:59:59)."""
    start = f"{start_date} 00:00:00"
    end = f"{end_date} 23:59:59"
    return start, end


def _snapshot_bucket(
    snapshot_id: Optional[str],
    snapshot_at: Optional[datetime],
    created_at: datetime,
) -> str:
    if snapshot_id:
        return snapshot_id
    ts = snapshot_at or created_at
    return ts.strftime("%Y-%m-%d %H")


def _fetch_products(
    db: Session, start: str, end: str, channel: str,
) -> list:
    return (
        db.execute(
            text(
                """
                SELECT
                    product_name,
                    mall_name,
                    unit_price,
                    total_price,
                    quantity,
                    link,
                    image_url,
                    card_image_path,
                    calc_method,
                    COALESCE(snapshot_at, created_at) AS ts,
                    snapshot_id,
                    snapshot_at,
                    created_at,
                    COALESCE(calc_valid, 1) AS calc_valid
                FROM products
                WHERE COALESCE(snapshot_at, created_at) >= :start
                  AND COALESCE(snapshot_at, created_at) <= :end
                  AND channel = :channel
                """
            ),
            {"start": start, "end": end, "channel": channel},
        )
        .mappings()
        .all()
    )


# ── 1) Summary-level seller metrics ────────────────────────────────
def compute_seller_metrics(
    db: Session,
    *,
    start_date: str,
    end_date: str,
    threshold_price: int,
    channel: str = "naver",
) -> Dict[str, Any]:
    """Return summary dict: below_count, top5 sellers, global min."""
    start, end = _date_range(start_date, end_date)
    rows = _fetch_products(db, start, end, channel)

    # bucket by seller -> snapshot to keep one price per observation
    by_seller: Dict[str, Dict[str, Dict]] = defaultdict(dict)

    for r in rows:
        if int(r.get("calc_valid") or 1) != 1:
            continue
        seller = (r["mall_name"] or "").strip() or "(unknown)"
        bucket = _snapshot_bucket(
            r.get("snapshot_id"), r.get("snapshot_at"), r.get("created_at"),
        )
        cur = by_seller[seller].get(bucket)
        if cur is None or r["unit_price"] < cur["unit_price"]:
            by_seller[seller][bucket] = {
                "unit_price": int(r["unit_price"]),
                "ts": r["ts"],
                "seller": seller,
            }

    # aggregate per seller
    seller_stats: List[Dict[str, Any]] = []
    for seller, buckets in by_seller.items():
        items = list(buckets.values())
        below = [x for x in items if x["unit_price"] <= threshold_price]
        if not items:
            continue
        min_item = min(items, key=lambda x: (x["unit_price"], x["ts"]))
        seller_stats.append({
            "seller_name": seller,
            "below_count": len(below),
            "min_unit_price": min_item["unit_price"],
            "min_time": min_item["ts"],
        })

    below_sellers = [s for s in seller_stats if s["below_count"] > 0]
    below_sellers.sort(key=lambda x: x["min_unit_price"])

    # top 5 lowest-price sellers
    top5 = below_sellers[:5]

    # global min
    global_min_seller = None
    global_min_price = None
    global_min_time = None
    if below_sellers:
        g = below_sellers[0]
        global_min_seller = g["seller_name"]
        global_min_price = g["min_unit_price"]
        global_min_time = g["min_time"]

    return {
        "below_threshold_seller_count": len(below_sellers),
        "top5_lowest": [
            {
                "seller_name": s["seller_name"],
                "min_unit_price": s["min_unit_price"],
                "min_time": s["min_time"],
            }
            for s in top5
        ],
        "global_min_seller": global_min_seller,
        "global_min_price": global_min_price,
        "global_min_time": global_min_time,
    }


# ── 2) Below-threshold detail list (grouped by seller) ─────────────
def compute_below_threshold_detail(
    db: Session,
    *,
    start_date: str,
    end_date: str,
    threshold_price: int,
    channel: str = "naver",
) -> List[Dict[str, Any]]:
    """Return seller-grouped below-threshold data.

    Each entry = {
        seller_name, platform, min_unit_price, min_time, ..., card_html,
        snapshots: [ {unit_price, total_price, quantity, time, link, ...}, ... ]
    }
    Top-level fields = seller's overall min (토글 닫힌 상태).
    snapshots = 스냅샷별 전체 목록 (토글 열린 상태).
    """
    start, end = _date_range(start_date, end_date)
    rows = _fetch_products(db, start, end, channel)

    # per seller+bucket keep the lowest-price record
    by_seller: Dict[str, Dict[str, Dict]] = defaultdict(dict)
    for r in rows:
        if int(r.get("calc_valid") or 1) != 1:
            continue
        price = int(r["unit_price"])
        if price > threshold_price:
            continue
        seller = (r["mall_name"] or "").strip() or "(unknown)"
        bucket = _snapshot_bucket(
            r.get("snapshot_id"), r.get("snapshot_at"), r.get("created_at"),
        )
        cur = by_seller[seller].get(bucket)
        if cur is None or price < cur["unit_price"]:
            by_seller[seller][bucket] = {
                "seller_name": seller,
                "platform": channel,
                "unit_price": price,
                "total_price": int(r.get("total_price") or 0),
                "quantity": int(r.get("quantity") or 0),
                "time": r["ts"],
                "link": r.get("link"),
                "image_url": r.get("image_url"),
                "product_name": r.get("product_name"),
                "calc_method": r.get("calc_method"),
                "card_image_path": r.get("card_image_path"),
            }

    result: List[Dict[str, Any]] = []
    for seller, buckets in by_seller.items():
        all_snapshots = sorted(buckets.values(), key=lambda x: (x["time"], x["unit_price"]))
        # seller-level min
        min_item = min(all_snapshots, key=lambda x: (x["unit_price"], x["time"]))
        result.append({
            **min_item,
            "snapshots": all_snapshots,
        })

    result.sort(key=lambda x: (x["unit_price"], x["time"]))
    return result


# ── 3) Seller chart data (per-snapshot) ─────────────────────────────
def compute_seller_chart_data(
    db: Session,
    *,
    start_date: str,
    end_date: str,
    seller_names: Optional[List[str]] = None,
    channel: str = "naver",
) -> Dict[str, List[Dict[str, Any]]]:
    """Return {seller_name: [{date, time, min_price}, ...]} per crawl snapshot.

    Each crawl session (00, 03, 12, 18 etc.) produces one point per seller.
    x-axis: date (YYYY-MM-DD), but multiple points per day.
    """
    start, end = _date_range(start_date, end_date)
    rows = _fetch_products(db, start, end, channel)

    # bucket by seller -> (date, hour_bucket) -> min price
    # hour_bucket groups nearby timestamps into crawl sessions
    by_seller_slot: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)

    for r in rows:
        if int(r.get("calc_valid") or 1) != 1:
            continue
        seller = (r["mall_name"] or "").strip() or "(unknown)"
        if seller_names and seller not in seller_names:
            continue
        price = int(r["unit_price"])
        ts = r["ts"]
        if isinstance(ts, datetime):
            date_str = ts.strftime("%Y-%m-%d")
            time_str = ts.strftime("%H:%M")
        else:
            date_str = str(ts)[:10]
            time_str = str(ts)[11:16]

        # Use snapshot_id if available, otherwise bucket by hour
        snap = r.get("snapshot_id")
        if snap:
            slot_key = f"{date_str}_{snap}"
        else:
            slot_key = f"{date_str}_{time_str[:2]}"

        cur = by_seller_slot[seller].get(slot_key)
        if cur is None or price < cur["min_price"]:
            by_seller_slot[seller][slot_key] = {
                "date": date_str,
                "time": time_str,
                "min_price": price,
            }

    result: Dict[str, List[Dict[str, Any]]] = {}
    for seller, slot_map in by_seller_slot.items():
        points = sorted(
            slot_map.values(),
            key=lambda x: (x["date"], x["time"]),
        )
        result[seller] = points

    return result
