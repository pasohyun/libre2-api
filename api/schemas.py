# api/schemas.py
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class Product(BaseModel):
    product_name: str
    unit_price: int
    quantity: int
    total_price: int
    mall_name: str
    calc_method: str
    link: str
    image_url: str

class ProductListResponse(BaseModel):
    snapshot_time: Optional[datetime] = None
    count: int
    data: List[Product]
