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
