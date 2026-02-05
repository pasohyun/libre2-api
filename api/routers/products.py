# api/routers/products.py
from fastapi import APIRouter, Query, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from api.database import SessionLocal
from api.schemas import ProductListResponse
from datetime import datetime

router = APIRouter(prefix="/products")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/latest", response_model=ProductListResponse)
def get_latest_products(db: Session = Depends(get_db)):
    try:
        rows = db.execute(text("""
            SELECT 
                keyword, product_name, unit_price, quantity, total_price,
                mall_name, calc_method, link, image_url, card_image_path,
                channel, market, created_at
            FROM products
            WHERE created_at = (
                SELECT MAX(created_at) FROM products
            )
            ORDER BY unit_price ASC
        """)).mappings().all()

        snapshot_time = rows[0]["created_at"] if rows else None

        return {
            "snapshot_time": snapshot_time,
            "count": len(rows),
            "data": rows
        }
    except Exception as e:
        import traceback
        error_detail = f"Database error: {str(e)}\n{traceback.format_exc()}"
        print(f"Error in get_latest_products: {error_detail}")  # 로그에 출력
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
        print(f"Error in get_lowest_products: {error_detail}")  # 로그에 출력
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/malls/stats")
def get_mall_statistics(db: Session = Depends(get_db)):
    """
    판매처별 통계 조회
    - 상품 수, 최저가, 평균가, 최근 등장 횟수
    """
    try:
        # 전체 기간 판매처별 통계
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
    """
    try:
        rows = db.execute(text("""
            SELECT 
                mall_name,
                MIN(unit_price) as lowest_price,
                COUNT(*) as product_count,
                ROUND(AVG(unit_price)) as avg_price
            FROM products
            WHERE created_at = (SELECT MAX(created_at) FROM products)
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
