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
                product_name, unit_price, quantity, total_price,
                mall_name, calc_method, link, image_url, created_at
            FROM products
            WHERE created_at = (
                SELECT MAX(created_at) FROM products
            )
            ORDER BY unit_price ASC
        """)).mappings().all()

        # 데이터 변환: RowMapping을 dict로 변환
        products = []
        snapshot_time = None
        
        for row in rows:
            row_dict = dict(row)
            if snapshot_time is None:
                snapshot_time = row_dict.get("created_at")
            products.append({
                "product_name": row_dict.get("product_name", ""),
                "unit_price": row_dict.get("unit_price", 0),
                "quantity": row_dict.get("quantity", 0),
                "total_price": row_dict.get("total_price", 0),
                "mall_name": row_dict.get("mall_name", ""),
                "calc_method": row_dict.get("calc_method", ""),
                "link": row_dict.get("link", ""),
                "image_url": row_dict.get("image_url", ""),
            })

        return {
            "snapshot_time": snapshot_time,
            "count": len(products),
            "data": products
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

        # 데이터 변환: RowMapping을 dict로 변환
        products = []
        for row in rows:
            row_dict = dict(row)
            products.append({
                "product_name": row_dict.get("product_name", ""),
                "unit_price": row_dict.get("unit_price", 0),
                "mall_name": row_dict.get("mall_name", ""),
                "link": row_dict.get("link", ""),
            })

        return {
            "limit": limit,
            "data": products
        }
    except Exception as e:
        import traceback
        error_detail = f"Database error: {str(e)}\n{traceback.format_exc()}"
        print(f"Error in get_lowest_products: {error_detail}")  # 로그에 출력
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
