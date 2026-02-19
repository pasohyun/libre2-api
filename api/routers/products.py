# api/routers/products.py
from fastapi import APIRouter, Query, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from api.database import SessionLocal
from api.schemas import ProductListResponse
from datetime import datetime, timedelta
import config

router = APIRouter(prefix="/products")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/latest", response_model=ProductListResponse)
def get_latest_products(db: Session = Depends(get_db)):
    """
    최신 스냅샷 기준 상품 리스트
    - snapshot_at이 있으면 snapshot_at을 기준으로 최신 스냅샷을 잡고,
    - 없으면 created_at을 기준으로 잡는다.
    """
    try:
        rows = db.execute(text("""
            SELECT 
                keyword, product_name, unit_price, quantity, total_price,
                mall_name, calc_method, link, image_url, card_image_path,
                channel, market,
                COALESCE(snapshot_at, created_at) AS snapshot_time
            FROM products
            WHERE COALESCE(snapshot_at, created_at) = (
                SELECT MAX(COALESCE(snapshot_at, created_at)) FROM products
            )
            ORDER BY unit_price ASC
        """)).mappings().all()

        snapshot_time = rows[0]["snapshot_time"] if rows else None

        return {
            "snapshot_time": snapshot_time,
            "count": len(rows),
            "data": rows
        }
    except Exception as e:
        import traceback
        error_detail = f"Database error: {str(e)}\n{traceback.format_exc()}"
        print(f"Error in get_latest_products: {error_detail}")
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

        return {
            "limit": limit,
            "data": rows
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

        return {
            "description": "판매처별 전체 기간 통계 (상품 수 기준 정렬)",
            "count": len(rows),
            "data": rows
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
            SELECT 
                mall_name,
                MIN(unit_price) as lowest_price,
                COUNT(*) as product_count,
                ROUND(AVG(unit_price)) as avg_price
            FROM products
            WHERE COALESCE(snapshot_at, created_at) = (
                SELECT MAX(COALESCE(snapshot_at, created_at)) FROM products
            )
            GROUP BY mall_name
            ORDER BY lowest_price ASC
            LIMIT :limit
        """), {"limit": limit}).mappings().all()

        return {
            "description": "최근 크롤링 기준 판매처별 최저가 (낮은 순)",
            "count": len(rows),
            "data": rows
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
        "tracked_malls": config.TRACKED_MALLS,
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
            SELECT 
                product_name, unit_price, quantity, total_price,
                mall_name, calc_method, link, image_url,
                COALESCE(snapshot_at, created_at) AS snapshot_time
            FROM products
            WHERE COALESCE(snapshot_at, created_at) = (
                SELECT MAX(COALESCE(snapshot_at, created_at)) FROM products
            )
              AND unit_price <= :target_price
            ORDER BY unit_price ASC
        """), {"target_price": price}).mappings().all()

        snapshot_time = rows[0]["snapshot_time"] if rows else None

        return {
            "target_price": price,
            "snapshot_time": snapshot_time,
            "count": len(rows),
            "data": rows
        }
    except Exception as e:
        import traceback
        print(f"Error in get_products_below_target: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/tracked-malls/summary")
def get_tracked_malls_summary(
    malls: str = Query(None, description="판매처 목록 (쉼표 구분, 미지정시 설정값 사용)"),
    db: Session = Depends(get_db)
):
    """
    주요 판매처 요약 (카드 표시용)
    - 현재 단가, 최근 7일 변동폭, 기준가 이하 횟수
    """
    if malls:
        mall_list = [m.strip() for m in malls.split(",") if m.strip()]
    elif config.TRACKED_MALLS:
        mall_list = config.TRACKED_MALLS
    else:
        top_malls = db.execute(text("""
            SELECT mall_name
            FROM products
            WHERE COALESCE(snapshot_at, created_at) = (
                SELECT MAX(COALESCE(snapshot_at, created_at)) FROM products
            )
            GROUP BY mall_name
            ORDER BY MIN(unit_price) ASC
            LIMIT 5
        """)).fetchall()
        mall_list = [row[0] for row in top_malls]

    if not mall_list:
        return {"target_price": config.TARGET_PRICE, "data": []}

    try:
        results = []
        for mall_name in mall_list:
            current = db.execute(text("""
                SELECT MIN(unit_price) as current_price
                FROM products
                WHERE mall_name = :mall_name
                  AND COALESCE(snapshot_at, created_at) = (
                      SELECT MAX(COALESCE(snapshot_at, created_at)) FROM products
                  )
            """), {"mall_name": mall_name}).fetchone()

            current_price = current[0] if current and current[0] else None

            week_stats = db.execute(text("""
                SELECT 
                    MIN(unit_price) as min_price,
                    MAX(unit_price) as max_price
                FROM (
                    SELECT MIN(unit_price) as unit_price, DATE(created_at) as date
                    FROM products
                    WHERE mall_name = :mall_name
                      AND created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                    GROUP BY DATE(created_at)
                ) daily_prices
            """), {"mall_name": mall_name}).fetchone()

            min_7d = week_stats[0] if week_stats and week_stats[0] else current_price
            max_7d = week_stats[1] if week_stats and week_stats[1] else current_price
            change_7d = (max_7d - min_7d) if min_7d and max_7d else 0

            below_count = db.execute(text("""
                SELECT COUNT(DISTINCT DATE(created_at)) as count
                FROM products
                WHERE mall_name = :mall_name
                  AND unit_price <= :target_price
                  AND created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            """), {"mall_name": mall_name, "target_price": config.TARGET_PRICE}).fetchone()

            results.append({
                "mall_name": mall_name,
                "current_price": current_price,
                "min_price_7d": min_7d,
                "max_price_7d": max_7d,
                "change_7d": change_7d,
                "below_target_count": below_count[0] if below_count else 0
            })

        return {
            "target_price": config.TARGET_PRICE,
            "tracked_malls": mall_list,
            "data": results
        }
    except Exception as e:
        import traceback
        print(f"Error in get_tracked_malls_summary: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/tracked-malls/trends")
def get_tracked_malls_trends(
    malls: str = Query(None, description="판매처 목록 (쉼표 구분)"),
    days: int = Query(7, ge=1, le=30, description="조회 기간 (일)"),
    db: Session = Depends(get_db)
):
    """
    주요 판매처 일별 가격 추이 (그래프용)
    - 각 판매처의 일별 최저가
    """
    if malls:
        mall_list = [m.strip() for m in malls.split(",") if m.strip()]
    elif config.TRACKED_MALLS:
        mall_list = config.TRACKED_MALLS
    else:
        top_malls = db.execute(text("""
            SELECT mall_name
            FROM products
            WHERE COALESCE(snapshot_at, created_at) = (
                SELECT MAX(COALESCE(snapshot_at, created_at)) FROM products
            )
            GROUP BY mall_name
            ORDER BY MIN(unit_price) ASC
            LIMIT 5
        """)).fetchall()
        mall_list = [row[0] for row in top_malls]

    if not mall_list:
        return {"days": days, "malls": [], "data": []}

    try:
        rows = db.execute(text("""
            SELECT 
                DATE(created_at) as date,
                mall_name,
                MIN(unit_price) as price
            FROM products
            WHERE mall_name IN :mall_list
              AND created_at >= DATE_SUB(NOW(), INTERVAL :days DAY)
            GROUP BY DATE(created_at), mall_name
            ORDER BY date ASC
        """), {"mall_list": tuple(mall_list), "days": days}).fetchall()

        date_data = {}
        for row in rows:
            date_str = row[0].strftime("%m/%d") if hasattr(row[0], 'strftime') else str(row[0])
            if date_str not in date_data:
                date_data[date_str] = {"date": date_str}
            date_data[date_str][row[1]] = row[2]

        trend_data = list(date_data.values())

        return {
            "days": days,
            "malls": mall_list,
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
    db: Session = Depends(get_db)
):
    """
    특정 판매처의 일별 가격 히스토리 (타임라인)
    - 일별 최저가 상품 정보 (상품명, 가격, 수량, 단가, 링크, 이미지 등)
    """
    try:
        rows = db.execute(text("""
            SELECT 
                p.product_name,
                p.unit_price,
                p.quantity,
                p.total_price,
                p.link,
                p.image_url,
                p.calc_method,
                p.created_at
            FROM products p
            WHERE p.mall_name = :mall_name
              AND p.created_at >= DATE_SUB(NOW(), INTERVAL :days DAY)
            ORDER BY p.created_at DESC
        """), {"mall_name": mall_name, "days": days}).fetchall()

        daily_best = {}
        for row in rows:
            date_key = row[7].strftime("%Y-%m-%d") if hasattr(row[7], 'strftime') else str(row[7])[:10]
            unit_price = row[1]

            if date_key not in daily_best or unit_price < daily_best[date_key]["unitPrice"]:
                daily_best[date_key] = {
                    "capturedAt": row[7].strftime("%Y-%m-%d %H:%M") if hasattr(row[7], 'strftime') else str(row[7]),
                    "date": date_key,
                    "productName": row[0],
                    "unitPrice": row[1],
                    "pack": row[2],
                    "price": row[3],
                    "url": row[4] or "#",
                    "captureThumb": row[5] or "",
                    "calcMethod": row[6],
                }

        timeline = [daily_best[k] for k in sorted(daily_best.keys(), reverse=True)]

        return {
            "mall_name": mall_name,
            "days": days,
            "count": len(timeline),
            "data": timeline
        }
    except Exception as e:
        import traceback
        print(f"Error in get_mall_timeline: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
