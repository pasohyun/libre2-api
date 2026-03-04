from __future__ import annotations

# api/schemas.py
from pydantic import BaseModel
from typing import List, Optional, Any, Dict
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
    card_image_path: str | None = None
    channel: str | None = None
    market: str | None = None

class ProductListResponse(BaseModel):
    snapshot_time: Optional[datetime] = None
    count: int
    data: List[Product]

class MonthlySellerMetric(BaseModel):
    month: str
    threshold_price: int
    channel: str
    seller_name_std: str

    observations: int
    below_threshold_count: int
    below_ratio: float

    min_unit_price: Optional[int] = None
    min_time: Optional[datetime] = None
    last_below_time: Optional[datetime] = None

    volatility: Optional[float] = None
    representative_links: Optional[Dict[str, Any]] = None
    calc_method_stats: Optional[Dict[str, Any]] = None

    dip_recover_count: Optional[int] = None
    sustained_below_count: Optional[int] = None
    cross_platform_mismatch: Optional[bool] = None


class MonthlyReportResponse(BaseModel):
    month: str
    threshold_price: int
    channel: str

    conclusion: Dict[str, Any]
    priority_list: List[Dict[str, Any]]
    seller_cards: List[Dict[str, Any]]
    patterns: List[Dict[str, Any]]
    data_quality: Dict[str, Any]

    llm: Optional[Dict[str, Any]] = None
    generated_at: Optional[datetime] = None