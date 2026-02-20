from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.database import SessionLocal
from api.schemas import MonthlyReportResponse
from api.services.monthly_report_builder import build_monthly_report, render_markdown

router = APIRouter(prefix="/reports", tags=["reports"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/monthly/{month}", response_model=MonthlyReportResponse)
def get_monthly_report(
    month: str,
    threshold_price: int = Query(..., description="Threshold price (KRW)"),
    channel: str = Query("naver", description="Channel/platform identifier"),
    crawl_schedule: str = Query("00/12", description="e.g. 00/12"),
    top_cards: int = Query(10, ge=0, le=50),
    use_llm: bool = Query(True, description="Generate LLM sections (requires OPENAI_API_KEY)"),
    store: bool = Query(False, description="Store metrics/report into DB"),
    db: Session = Depends(get_db),
):
    report = build_monthly_report(
        db,
        month=month,
        threshold_price=threshold_price,
        channel=channel,
        crawl_schedule=crawl_schedule,
        platforms=[channel],
        top_cards=top_cards,
        use_llm=use_llm,
        store=store,
    )
    return report


@router.get("/monthly/{month}/markdown")
def get_monthly_report_markdown(
    month: str,
    threshold_price: int = Query(..., description="Threshold price (KRW)"),
    channel: str = Query("naver", description="Channel/platform identifier"),
    crawl_schedule: str = Query("00/12", description="e.g. 00/12"),
    top_cards: int = Query(10, ge=0, le=50),
    use_llm: bool = Query(True),
    store: bool = Query(False),
    db: Session = Depends(get_db),
):
    report = build_monthly_report(
        db,
        month=month,
        threshold_price=threshold_price,
        channel=channel,
        crawl_schedule=crawl_schedule,
        platforms=[channel],
        top_cards=top_cards,
        use_llm=use_llm,
        store=store,
    )
    return {
        "month": month,
        "channel": channel,
        "threshold_price": threshold_price,
        "markdown": render_markdown(report),
    }
