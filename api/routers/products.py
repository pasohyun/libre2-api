# api/routers/products.py
from fastapi import APIRouter, Query, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import text
from api.database import SessionLocal
from api.schemas import ProductListResponse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import threading
import os
import uuid
import config

router = APIRouter(prefix="/products")
KST = ZoneInfo("Asia/Seoul")
_crawl_lock = threading.Lock()
_crawl_running = False
_crawl_last_started_at_kst = None
_crawl_last_finished_at_kst = None
_crawl_last_error = None

try:
    from api.services.card_renderer import render_card_png
    _card_renderer_import_error = None
except Exception as e:
    render_card_png = None
    _card_renderer_import_error = e

try:
    from api.services.s3_storage import (
        is_s3_enabled,
        upload_bytes,
        generate_presigned_url,
        extract_object_key,
    )
    _s3_storage_import_error = None
except Exception as e:
    is_s3_enabled = None
    upload_bytes = None
    generate_presigned_url = None
    extract_object_key = None
    _s3_storage_import_error = e


def _to_kst(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        # products.snapshot_at is saved as KST-naive datetime in current DB flow.
        # Treat naive values as KST to avoid double +9h conversion on response.
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


def _run_crawl_job():
    global _crawl_running, _crawl_last_started_at_kst, _crawl_last_finished_at_kst, _crawl_last_error
    try:
        from scripts.crawl_naver import run_crawling

        _crawl_last_started_at_kst = datetime.now(KST)
        _crawl_last_error = None
        run_crawling()
    except Exception as e:
        _crawl_last_error = str(e)
    finally:
        _crawl_last_finished_at_kst = datetime.now(KST)
        with _crawl_lock:
            _crawl_running = False


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _to_display_image_url(value: str | None) -> str | None:
    """
    S3 private 객체는 presigned URL로 바꿔서 내려준다.
    외부 이미지 URL(네이버 썸네일 등)은 원본 유지.
    """
    raw = (value or "").strip()
    if not raw:
        return None

    if (
        _s3_storage_import_error is None
        and is_s3_enabled is not None
        and generate_presigned_url is not None
        and extract_object_key is not None
        and is_s3_enabled()
    ):
        key = extract_object_key(raw)
        if key:
            signed = generate_presigned_url(key, expires_in=3600)
            if signed:
                return signed
    return raw


_MALL_NAME_DB_TO_PUBLIC = {
    "랜식": "랜식(글핏몰)",
    "글핏몰": "랜식(글핏몰)",
    "글루코핏": "랜식(글핏몰)",
    "글루어트": "랜식(글핏몰)",
    "닥터다이어리": "닥터다이어리(닥다몰)",
    "닥다몰": "닥터다이어리(닥다몰)",
    "무화당": "닥터다이어리(무화당)",
}
_MALL_NAME_PUBLIC_TO_DB_CANDIDATES = {
    "랜식(글핏몰)": ("랜식", "글핏몰", "글루코핏", "글루어트"),
    "닥터다이어리(닥다몰)": ("닥다몰", "닥터다이어리"),
    "닥터다이어리(무화당)": ("무화당",),
}


def _to_public_mall_name(name: str | None) -> str:
    raw = (name or "").strip()
    if not raw:
        return ""
    return _MALL_NAME_DB_TO_PUBLIC.get(raw, raw)


def _to_db_mall_name(name: str | None) -> str:
    raw = (name or "").strip()
    if not raw:
        return ""
    # 공개 표준명이 들어오면 DB 후보군의 대표 키로 변환한다.
    candidates = _MALL_NAME_PUBLIC_TO_DB_CANDIDATES.get(raw)
    if candidates:
        return candidates[0]
    return raw


def _mall_name_candidates(name: str | None) -> tuple[str, ...]:
    """
    DB에 구명칭/신명칭이 혼재해도 조회되도록 후보 목록을 만든다.
    예) 글루코핏 -> (글루코핏, 글루어트)
    """
    public_name = _to_public_mall_name(name)
    values = [public_name, (name or "").strip()]
    for candidate in _MALL_NAME_PUBLIC_TO_DB_CANDIDATES.get(public_name, ()):
        values.append(candidate)
    # 빈 문자열 제거 + 순서 유지 dedupe
    result = []
    seen = set()
    for v in values:
        if not v or v in seen:
            continue
        seen.add(v)
        result.append(v)
    return tuple(result)


def _mall_name_std_sql(column_name: str) -> str:
    """
    SQL에서 판매처명을 표준명으로 통합하기 위한 CASE 식.
    """
    return (
        f"CASE TRIM({column_name}) "
        "WHEN '랜식' THEN '랜식(글핏몰)' "
        "WHEN '글핏몰' THEN '랜식(글핏몰)' "
        "WHEN '글루코핏' THEN '랜식(글핏몰)' "
        "WHEN '글루어트' THEN '랜식(글핏몰)' "
        "WHEN '닥터다이어리' THEN '닥터다이어리(닥다몰)' "
        "WHEN '닥다몰' THEN '닥터다이어리(닥다몰)' "
        "WHEN '무화당' THEN '닥터다이어리(무화당)' "
        f"ELSE TRIM({column_name}) END"
    )


@router.get("/latest", response_model=ProductListResponse)
def get_latest_products(db: Session = Depends(get_db)):
    """
    최신 스냅샷 기준 상품 리스트
    - snapshot_at이 있으면 snapshot_at을 기준으로 최신 스냅샷을 잡고,
    - 없으면 created_at을 기준으로 잡는다.
    """
    try:
        rows = db.execute(text("""
            WITH latest_naver AS (
                SELECT snapshot_id
                FROM products
                WHERE snapshot_id IS NOT NULL
                  AND market != '쿠팡'
                ORDER BY snapshot_id DESC
                LIMIT 1
            ),
            latest_coupang_brand AS (
                SELECT snapshot_id
                FROM products
                WHERE snapshot_id IS NOT NULL
                  AND market = '쿠팡'
                ORDER BY snapshot_id DESC
                LIMIT 1
            ),
            coupang_brand_keys AS (
                SELECT product_name, quantity
                FROM products
                WHERE snapshot_id = (SELECT snapshot_id FROM latest_coupang_brand)
            )
            SELECT
                p.id,
                keyword, product_name, unit_price, quantity, total_price,
                mall_name, calc_method, link,
                p.image_url AS image_url,
                card_image_path,
                p.channel, market,
                COALESCE(p.snapshot_at, p.created_at) AS snapshot_time
            FROM products p
            WHERE (
                p.snapshot_id = (SELECT snapshot_id FROM latest_coupang_brand)
            ) OR (
                p.snapshot_id = (SELECT snapshot_id FROM latest_naver)
                AND NOT EXISTS (
                    SELECT 1 FROM coupang_brand_keys cb
                    WHERE cb.product_name = p.product_name
                      AND cb.quantity = p.quantity
                )
            )
            ORDER BY unit_price ASC
        """)).mappings().all()

        data = []
        for r in rows:
            item = dict(r)
            signed_card = _to_display_image_url(item.get("card_image_path"))
            item["card_image_path"] = signed_card
            # HTML 카드 미리보기는 원본 사이트 이미지를 유지한다.
            item["image_url"] = item.get("image_url") or ""
            item["mall_name"] = _to_public_mall_name(item.get("mall_name"))
            data.append(item)

        snapshot_time = _to_kst(rows[0]["snapshot_time"]) if rows else None

        return {
            "snapshot_time": snapshot_time,
            "count": len(data),
            "data": data
        }
    except Exception as e:
        import traceback
        error_detail = f"Database error: {str(e)}\n{traceback.format_exc()}"
        print(f"Error in get_latest_products: {error_detail}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/today", response_model=ProductListResponse)
def get_today_products(db: Session = Depends(get_db)):
    """
    KST 기준 오늘(00:00~24:00) 누적 크롤링 상품 전체
    """
    try:
        now_kst = datetime.now(KST)
        day_start_kst = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end_kst = day_start_kst + timedelta(days=1)

        # DB에는 KST-naive 시각을 저장하므로 tzinfo 제거 후 범위를 비교한다.
        day_start = day_start_kst.replace(tzinfo=None)
        day_end = day_end_kst.replace(tzinfo=None)

        rows = db.execute(text("""
            SELECT
                p.id,
                keyword, product_name, unit_price, quantity, total_price,
                mall_name, calc_method, link,
                p.image_url AS image_url,
                card_image_path,
                channel, market,
                COALESCE(p.snapshot_at, p.created_at) AS snapshot_time
            FROM products p
            WHERE COALESCE(p.snapshot_at, p.created_at) >= :day_start
              AND COALESCE(p.snapshot_at, p.created_at) < :day_end
            ORDER BY COALESCE(p.snapshot_at, p.created_at) DESC, unit_price ASC, id DESC
        """), {"day_start": day_start, "day_end": day_end}).mappings().all()

        data = []
        for r in rows:
            item = dict(r)
            signed_card = _to_display_image_url(item.get("card_image_path"))
            item["card_image_path"] = signed_card
            item["image_url"] = item.get("image_url") or ""
            item["mall_name"] = _to_public_mall_name(item.get("mall_name"))
            data.append(item)

        snapshot_time = _to_kst(rows[0]["snapshot_time"]) if rows else None
        return {
            "snapshot_time": snapshot_time,
            "count": len(data),
            "data": data,
        }
    except Exception as e:
        import traceback
        error_detail = f"Database error: {str(e)}\n{traceback.format_exc()}"
        print(f"Error in get_today_products: {error_detail}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/lowest")
def get_lowest_products(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db)
):
    try:
        rows = db.execute(text("""
            SELECT product_name, unit_price, mall_name, link
            FROM products
            ORDER BY unit_price ASC
            LIMIT :limit
        """), {"limit": limit}).mappings().all()

        data = []
        for r in rows:
            item = dict(r)
            item["mall_name"] = _to_public_mall_name(item.get("mall_name"))
            data.append(item)

        return {
            "limit": limit,
            "data": data
        }
    except Exception as e:
        import traceback
        error_detail = f"Database error: {str(e)}\n{traceback.format_exc()}"
        print(f"Error in get_lowest_products: {error_detail}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/malls/stats")
def get_mall_statistics(db: Session = Depends(get_db)):
    """
    판매처별 통계 조회
    - 상품 수, 최저가, 평균가, 최근 등장 횟수
    """
    try:
        rows = db.execute(text("""
            SELECT 
                mall_name,
                COUNT(*) as total_count,
                MIN(unit_price) as min_price,
                MAX(unit_price) as max_price,
                ROUND(AVG(unit_price)) as avg_price,
                COUNT(DISTINCT DATE(created_at)) as days_appeared
            FROM products
            GROUP BY mall_name
            ORDER BY total_count DESC
            LIMIT 50
        """)).mappings().all()

        data = []
        for r in rows:
            item = dict(r)
            item["mall_name"] = _to_public_mall_name(item.get("mall_name"))
            data.append(item)

        return {
            "description": "판매처별 전체 기간 통계 (상품 수 기준 정렬)",
            "count": len(data),
            "data": data
        }
    except Exception as e:
        import traceback
        print(f"Error in get_mall_statistics: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/malls/top")
def get_top_malls(
    limit: int = Query(10, ge=1, le=30),
    db: Session = Depends(get_db)
):
    """
    주요 판매처 TOP N (최근 크롤링 기준, 최저가 순)
    - snapshot_at이 있으면 snapshot_at 기준 최신 스냅샷,
    - 없으면 created_at 기준 최신 스냅샷
    """
    try:
        rows = db.execute(text("""
            WITH latest AS (
                SELECT snapshot_id, COALESCE(snapshot_at, created_at) AS snapshot_time
                FROM products
                ORDER BY COALESCE(snapshot_at, created_at) DESC, id DESC
                LIMIT 1
            )
            SELECT 
                mall_name,
                MIN(unit_price) as lowest_price,
                COUNT(*) as product_count,
                ROUND(AVG(unit_price)) as avg_price
            FROM products p
            CROSS JOIN latest l
            WHERE (
                (l.snapshot_id IS NOT NULL AND p.snapshot_id = l.snapshot_id)
                OR (l.snapshot_id IS NULL AND COALESCE(p.snapshot_at, p.created_at) = l.snapshot_time)
            )
            GROUP BY mall_name
            ORDER BY lowest_price ASC
            LIMIT :limit
        """), {"limit": limit}).mappings().all()

        data = []
        for r in rows:
            item = dict(r)
            item["mall_name"] = _to_public_mall_name(item.get("mall_name"))
            data.append(item)

        return {
            "description": "최근 크롤링 기준 판매처별 최저가 (낮은 순)",
            "count": len(data),
            "data": data
        }
    except Exception as e:
        import traceback
        print(f"Error in get_top_malls: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


# ============================================================
# 기준가 이하 상품 & 주요 판매처 API
# ============================================================

@router.get("/config")
def get_config():
    """
    현재 설정값 조회 (기준가, 주요 판매처 목록)
    """
    return {
        "target_price": config.TARGET_PRICE,
        "tracked_malls": [_to_public_mall_name(m) for m in config.TRACKED_MALLS],
        "search_keyword": config.SEARCH_KEYWORD
    }


@router.get("/below-target")
def get_products_below_target(
    target_price: int = Query(None, description="기준가 (미지정시 설정값 사용)"),
    db: Session = Depends(get_db)
):
    """
    기준가 이하 상품 목록 (최신 크롤링 기준)
    - 메인 대시보드에서 저렴한 상품 전체 표시용
    """
    price = target_price or config.TARGET_PRICE

    try:
        rows = db.execute(text("""
            WITH latest AS (
                SELECT snapshot_id, COALESCE(snapshot_at, created_at) AS snapshot_time
                FROM products
                ORDER BY COALESCE(snapshot_at, created_at) DESC, id DESC
                LIMIT 1
            )
            SELECT 
                product_name, unit_price, quantity, total_price,
                mall_name, calc_method, link,
                COALESCE(card_image_path, image_url) AS image_url,
                card_image_path,
                COALESCE(p.snapshot_at, p.created_at) AS snapshot_time
            FROM products p
            CROSS JOIN latest l
            WHERE (
                (l.snapshot_id IS NOT NULL AND p.snapshot_id = l.snapshot_id)
                OR (l.snapshot_id IS NULL AND COALESCE(p.snapshot_at, p.created_at) = l.snapshot_time)
            )
              AND unit_price <= :target_price
            ORDER BY unit_price ASC
        """), {"target_price": price}).mappings().all()

        snapshot_time = _to_kst(rows[0]["snapshot_time"]) if rows else None

        data = []
        for r in rows:
            item = dict(r)
            item["mall_name"] = _to_public_mall_name(item.get("mall_name"))
            data.append(item)

        return {
            "target_price": price,
            "snapshot_time": snapshot_time,
            "count": len(data),
            "data": data
        }
    except Exception as e:
        import traceback
        print(f"Error in get_products_below_target: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/tracked-malls/summary")
def get_tracked_malls_summary(
    malls: str = Query(None, description="판매처 목록 (쉼표 구분, 미지정시 설정값 사용)"),
    channel: str = Query(None, description="채널 필터 (naver, coupang, others)"),
    db: Session = Depends(get_db)
):
    """
    주요 판매처 요약 (카드 표시용)
    - 현재 단가, 최근 7일 변동폭, 기준가 이하 횟수
    - channel 파라미터로 특정 채널의 판매처만 조회 가능
    """
    # 채널 필터 SQL 조건 생성
    channel_filter_sql = ""
    channel_params = {}
    if channel:
        channel_filter_sql = " AND p.channel = :channel"
        channel_params["channel"] = channel

    if malls:
        mall_list = [_to_db_mall_name(m.strip()) for m in malls.split(",") if m.strip()]
    elif config.TRACKED_MALLS and not channel:
        mall_list = [_to_db_mall_name(m) for m in config.TRACKED_MALLS]
    elif channel == "naver":
        # 네이버 채널은 전체 기간에 한 번이라도 등장한 판매처를 모두 노출한다.
        mall_name_std_expr = _mall_name_std_sql("mall_name")
        all_naver_malls = db.execute(text(f"""
            SELECT {mall_name_std_expr} AS mall_name
            FROM products
            WHERE channel = :channel
            GROUP BY {mall_name_std_expr}
            ORDER BY COUNT(*) DESC, MIN(unit_price) ASC
        """), {"channel": channel}).fetchall()
        mall_list = [row[0] for row in all_naver_malls]
    else:
        top_malls = db.execute(text(f"""
            WITH latest AS (
                SELECT snapshot_id, COALESCE(snapshot_at, created_at) AS snapshot_time
                FROM products
                {"WHERE channel = :channel" if channel else ""}
                ORDER BY COALESCE(snapshot_at, created_at) DESC, id DESC
                LIMIT 1
            )
            SELECT mall_name
            FROM products p
            CROSS JOIN latest l
            WHERE (
                (l.snapshot_id IS NOT NULL AND p.snapshot_id = l.snapshot_id)
                OR (l.snapshot_id IS NULL AND COALESCE(p.snapshot_at, p.created_at) = l.snapshot_time)
            )
            {channel_filter_sql}
            GROUP BY mall_name
            ORDER BY MIN(unit_price) ASC
            LIMIT 10
        """), {**channel_params}).fetchall()
        mall_list = [row[0] for row in top_malls]

    if not mall_list:
        return {"target_price": config.TARGET_PRICE, "data": []}

    try:
        results = []
        for mall_name in mall_list:
            mall_name_list = _mall_name_candidates(mall_name)
            # 최신 스냅샷이 아닌 "해당 판매처의 최신 수집값"을 현재가로 사용한다.
            current = db.execute(text(f"""
                SELECT p.unit_price as current_price
                FROM products p
                WHERE p.mall_name IN :mall_name_list
                  {channel_filter_sql}
                ORDER BY COALESCE(p.snapshot_at, p.created_at) DESC, p.id DESC
                LIMIT 1
            """), {"mall_name_list": mall_name_list, **channel_params}).fetchone()

            current_price = current[0] if current and current[0] else None

            week_stats = db.execute(text(f"""
                SELECT
                    MIN(unit_price) as min_price,
                    MAX(unit_price) as max_price
                FROM (
                    SELECT MIN(unit_price) as unit_price, DATE(created_at) as date
                    FROM products p
                    WHERE mall_name IN :mall_name_list
                      AND created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                      {channel_filter_sql}
                    GROUP BY DATE(created_at)
                ) daily_prices
            """), {"mall_name_list": mall_name_list, **channel_params}).fetchone()

            min_7d = week_stats[0] if week_stats and week_stats[0] else current_price
            max_7d = week_stats[1] if week_stats and week_stats[1] else current_price
            change_7d = (max_7d - min_7d) if min_7d and max_7d else 0

            below_count = db.execute(text(f"""
                SELECT COUNT(DISTINCT DATE(created_at)) as count
                FROM products p
                WHERE mall_name IN :mall_name_list
                  AND unit_price <= :target_price
                  AND created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                  {channel_filter_sql}
            """), {"mall_name_list": mall_name_list, "target_price": config.TARGET_PRICE, **channel_params}).fetchone()

            results.append({
                "mall_name": _to_public_mall_name(mall_name),
                "current_price": current_price,
                "min_price_7d": min_7d,
                "max_price_7d": max_7d,
                "change_7d": change_7d,
                "below_target_count": below_count[0] if below_count else 0
            })

        public_malls = []
        seen_public = set()
        for m in mall_list:
            pm = _to_public_mall_name(m)
            if pm and pm not in seen_public:
                seen_public.add(pm)
                public_malls.append(pm)

        return {
            "target_price": config.TARGET_PRICE,
            "tracked_malls": public_malls,
            "data": results
        }
    except Exception as e:
        import traceback
        print(f"Error in get_tracked_malls_summary: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/tracked-malls/trends")
def get_tracked_malls_trends(
    malls: str = Query(None, description="판매처 목록 (쉼표 구분)"),
    days: int = Query(30, ge=1, le=90, description="조회 기간 (일)"),
    channel: str = Query(None, description="채널 필터 (naver, coupang, others)"),
    db: Session = Depends(get_db)
):
    """
    주요 판매처 일별 가격 추이 (그래프용)
    - 각 판매처의 일별 최저가
    - channel 파라미터로 특정 채널의 판매처만 조회 가능
    """
    # 채널 필터 SQL 조건 생성
    channel_filter_sql = ""
    channel_params = {}
    if channel:
        channel_filter_sql = " AND channel = :channel"
        channel_params["channel"] = channel

    if malls:
        mall_list = [_to_db_mall_name(m.strip()) for m in malls.split(",") if m.strip()]
    elif config.TRACKED_MALLS and not channel:
        mall_list = [_to_db_mall_name(m) for m in config.TRACKED_MALLS]
    else:
        top_malls = db.execute(text(f"""
            WITH latest AS (
                SELECT snapshot_id, COALESCE(snapshot_at, created_at) AS snapshot_time
                FROM products
                {"WHERE channel = :channel" if channel else ""}
                ORDER BY COALESCE(snapshot_at, created_at) DESC, id DESC
                LIMIT 1
            )
            SELECT mall_name
            FROM products p
            CROSS JOIN latest l
            WHERE (
                (l.snapshot_id IS NOT NULL AND p.snapshot_id = l.snapshot_id)
                OR (l.snapshot_id IS NULL AND COALESCE(p.snapshot_at, p.created_at) = l.snapshot_time)
            )
            {channel_filter_sql.replace("channel", "p.channel") if channel else ""}
            GROUP BY mall_name
            ORDER BY MIN(unit_price) ASC
            LIMIT 10
        """), {**channel_params}).fetchall()
        mall_list = [row[0] for row in top_malls]

    if not mall_list:
        return {"days": days, "malls": [], "data": []}

    try:
        mall_name_std_expr = _mall_name_std_sql("mall_name")

        rows = db.execute(text(f"""
            SELECT
                DATE(created_at) as date,
                {mall_name_std_expr} as mall_name,
                MIN(unit_price) as price
            FROM products
            WHERE {mall_name_std_expr} IN :mall_list
              AND created_at >= DATE_SUB(NOW(), INTERVAL :days DAY)
              {channel_filter_sql}
            GROUP BY DATE(created_at), {mall_name_std_expr}
            ORDER BY date ASC
        """), {"mall_list": tuple(mall_list), "days": days, **channel_params}).fetchall()

        date_data = {}
        for row in rows:
            date_str = row[0].strftime("%m/%d") if hasattr(row[0], 'strftime') else str(row[0])
            if date_str not in date_data:
                date_data[date_str] = {"date": date_str}
            mall_name = row[1]
            if mall_name in date_data[date_str]:
                # 이름 통합 과정에서 동일 키가 겹치면 더 낮은 가격을 사용
                date_data[date_str][mall_name] = min(date_data[date_str][mall_name], row[2])
            else:
                date_data[date_str][mall_name] = row[2]

        trend_data = list(date_data.values())
        public_malls = []
        seen_public = set()
        for m in mall_list:
            pm = _to_public_mall_name(m)
            if pm and pm not in seen_public:
                seen_public.add(pm)
                public_malls.append(pm)

        return {
            "days": days,
            "malls": public_malls,
            "data": trend_data
        }
    except Exception as e:
        import traceback
        print(f"Error in get_tracked_malls_trends: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/mall/timeline")
def get_mall_timeline(
    mall_name: str = Query(..., description="판매처 이름"),
    days: int = Query(30, ge=1, le=90, description="조회 기간 (일)"),
    channel: str = Query(None, description="채널 필터 (naver, coupang, others)"),
    db: Session = Depends(get_db)
):
    """
    특정 판매처의 크롤링 시점별 최저가 히스토리 (타임라인)
    - 스냅샷(또는 시간대)별 최저가 상품 정보
    """
    try:
        db_mall_name_list = _mall_name_candidates(mall_name)
        channel_filter_sql = ""
        params = {"mall_name_list": db_mall_name_list, "days": days}
        if channel:
            channel_filter_sql = " AND p.channel = :channel"
            params["channel"] = channel
        rows = db.execute(text(f"""
            SELECT
                p.product_name,
                p.id,
                p.unit_price,
                p.quantity,
                p.total_price,
                p.link,
                p.image_url,
                p.card_image_path,
                p.calc_method,
                COALESCE(p.snapshot_at, p.created_at) AS ts,
                p.snapshot_id
            FROM products p
            WHERE p.mall_name IN :mall_name_list
              AND COALESCE(p.snapshot_at, p.created_at) >= DATE_SUB(NOW(), INTERVAL :days DAY)
              {channel_filter_sql}
            ORDER BY COALESCE(p.snapshot_at, p.created_at) DESC
        """), params).fetchall()

        # 모든 크롤링 상품을 개별 항목으로 반환
        timeline_items = []
        for row in rows:
            ts_raw = row[9]
            captured_at_kst = _to_kst(ts_raw) if hasattr(ts_raw, "strftime") else None
            date_key = captured_at_kst.strftime("%Y-%m-%d") if captured_at_kst else str(ts_raw)[:10]
            signed_card = _to_display_image_url(row[7])
            timeline_items.append({
                "id": row[1],
                "capturedAt": captured_at_kst.strftime("%Y-%m-%d %H:%M") if captured_at_kst else str(ts_raw),
                "date": date_key,
                "time": captured_at_kst.strftime("%H:%M") if captured_at_kst else str(ts_raw)[11:16],
                "productName": row[0],
                "unitPrice": row[2],
                "pack": row[3],
                "price": row[4],
                "url": row[5] or "#",
                "captureThumb": row[6] or "",
                "cardImagePath": signed_card or "",
                "calcMethod": row[8],
            })

        timeline = sorted(timeline_items, key=lambda x: x["capturedAt"], reverse=True)

        return {
            "mall_name": _to_public_mall_name(mall_name),
            "days": days,
            "count": len(timeline),
            "data": timeline
        }
    except Exception as e:
        import traceback
        print(f"Error in get_mall_timeline: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.post("/crawl/run")
def run_crawl_now(background_tasks: BackgroundTasks):
    """
    수동 크롤링 실행 트리거 (대시보드 버튼용)
    - 이미 실행 중이면 중복 실행을 막는다.
    """
    global _crawl_running
    with _crawl_lock:
        if _crawl_running:
            return {
                "started": False,
                "message": "Crawling job is already running",
                "status": "running",
            }
        _crawl_running = True
    background_tasks.add_task(_run_crawl_job)
    return {"started": True, "message": "Crawling job started", "status": "started"}


@router.get("/crawl/status")
def get_crawl_status():
    return {
        "running": _crawl_running,
        "last_started_at": _crawl_last_started_at_kst,
        "last_finished_at": _crawl_last_finished_at_kst,
        "last_error": _crawl_last_error,
        "timezone": "Asia/Seoul",
    }


@router.post("/card/generate")
def generate_card_image(
    product_id: int = Query(..., ge=1, description="products.id"),
    db: Session = Depends(get_db)
):
    """
    단건 카드 이미지 생성/업로드 API
    - 기본 화면은 HTML 카드로 빠르게 표시
    - 필요한 경우에만 버튼 클릭으로 이미지 생성
    """
    if not config.ENABLE_CARD_RENDER:
        raise HTTPException(status_code=400, detail="ENABLE_CARD_RENDER is false")
    if _card_renderer_import_error is not None or render_card_png is None:
        raise HTTPException(status_code=500, detail=f"Card renderer unavailable: {_card_renderer_import_error}")
    if _s3_storage_import_error is not None or is_s3_enabled is None or upload_bytes is None:
        raise HTTPException(status_code=500, detail=f"S3 storage unavailable: {_s3_storage_import_error}")
    if not is_s3_enabled():
        raise HTTPException(status_code=400, detail="S3 is not enabled")

    row = db.execute(text("""
        SELECT id, keyword, product_name, unit_price, quantity, total_price,
               mall_name, calc_method, link, image_url, card_image_path, snapshot_id
        FROM products
        WHERE id = :pid
        LIMIT 1
    """), {"pid": product_id}).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Product not found")

    if row["card_image_path"]:
        existing_display = _to_display_image_url(row["card_image_path"]) or row["card_image_path"]
        return {
            "created": False,
            "product_id": product_id,
            "card_image_path": existing_display,
            "message": "Card image already exists",
        }

    product = {
        "product_name": row["product_name"],
        "mall_name": row["mall_name"],
        "link": row["link"],
        "image_url": row["image_url"],
        "unit_price": row["unit_price"],
        "total_price": row["total_price"],
        "quantity": row["quantity"],
        "calc_method": row["calc_method"],
    }

    captured_at = datetime.now(KST)
    bucket_prefix = config.S3_PREFIX.strip("/")
    snapshot_part = row["snapshot_id"] or captured_at.strftime("%Y%m%d")
    object_key = f"{bucket_prefix}/products/manual/{snapshot_part}/{product_id}_{uuid.uuid4().hex[:8]}.png"

    try:
        local_png_path = render_card_png(
            product=product,
            out_dir=os.path.join("product_cards", "manual", snapshot_part),
            captured_at=captured_at,
        )
        with open(local_png_path, "rb") as f:
            content = f.read()
        _ = upload_bytes(content=content, object_key=object_key, content_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Card generation failed: {e}")

    stored_value = object_key
    display_url = _to_display_image_url(stored_value) or stored_value

    link = (row["link"] or "").strip() if row.get("link") else ""
    if link:
        db.execute(
            text("UPDATE products SET card_image_path = :value WHERE link = :link"),
            {"value": stored_value, "link": link},
        )
    else:
        db.execute(
            text("UPDATE products SET card_image_path = :value WHERE id = :pid"),
            {"value": stored_value, "pid": product_id},
        )
    db.commit()

    return {
        "created": True,
        "product_id": product_id,
        "card_image_path": display_url,
        "message": "Card image generated and saved",
    }


@router.post("/manual-confirm")
def manual_confirm_quantity(
    product_id: int = Query(..., ge=1, description="products.id"),
    quantity: int = Query(..., ge=1, description="확정 수량(개)"),
    db: Session = Depends(get_db),
):
    """
    수동확인 대상의 수량을 확정하여 단가를 재계산한다.
    """
    row = db.execute(
        text("""
            SELECT id, total_price
            FROM products
            WHERE id = :pid
            LIMIT 1
        """),
        {"pid": product_id},
    ).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Product not found")

    total_price = int(row["total_price"] or 0)
    new_unit_price = total_price // quantity if quantity > 0 else total_price

    db.execute(
        text("""
            UPDATE products
            SET quantity = :quantity,
                unit_price = :unit_price,
                calc_method = :calc_method,
                calc_valid = 1
            WHERE id = :pid
        """),
        {
            "quantity": quantity,
            "unit_price": new_unit_price,
            "calc_method": "수동확인(완료)",
            "pid": product_id,
        },
    )
    db.commit()

    return {
        "updated": True,
        "product_id": product_id,
        "quantity": quantity,
        "unit_price": new_unit_price,
        "calc_method": "수동확인(완료)",
    }
