from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.database import SessionLocal
from api.schemas import DateRangeReportResponse, MonthlyReportResponse
from api.services.monthly_report_builder import build_monthly_report, render_markdown
from api.services.range_report_builder import build_range_report, render_range_markdown

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
    plats = ["naver", "coupang"] if channel == "all" else [channel]
    report = build_monthly_report(
        db,
        month=month,
        threshold_price=threshold_price,
        channel=channel,
        crawl_schedule=crawl_schedule,
        platforms=plats,
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
    plats = ["naver", "coupang"] if channel == "all" else [channel]
    report = build_monthly_report(
        db,
        month=month,
        threshold_price=threshold_price,
        channel=channel,
        crawl_schedule=crawl_schedule,
        platforms=plats,
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


# ── Date-Range Report endpoints ─────────────────────────────────────

def _validate_date_range(start_date: str, end_date: str) -> None:
    try:
        sd = datetime.strptime(start_date, "%Y-%m-%d").date()
        ed = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "start_date/end_date must be YYYY-MM-DD format")
    if sd > ed:
        raise HTTPException(400, "start_date must be <= end_date")
    if (ed - sd).days > 90:
        raise HTTPException(400, "Maximum date range is 90 days")


@router.get("/range", response_model=DateRangeReportResponse)
def get_range_report(
    start_date: str = Query(..., description="Start date (YYYY-MM-DD, inclusive)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD, inclusive)"),
    threshold_price: int = Query(..., description="Threshold price (KRW)"),
    channel: str = Query("naver", description="Channel/platform identifier"),
    db: Session = Depends(get_db),
):
    _validate_date_range(start_date, end_date)
    report = build_range_report(
        db,
        start_date=start_date,
        end_date=end_date,
        threshold_price=threshold_price,
        channel=channel,
    )
    return report


@router.get("/range/markdown")
def get_range_report_markdown(
    start_date: str = Query(..., description="Start date (YYYY-MM-DD, inclusive)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD, inclusive)"),
    threshold_price: int = Query(..., description="Threshold price (KRW)"),
    channel: str = Query("naver", description="Channel/platform identifier"),
    db: Session = Depends(get_db),
):
    _validate_date_range(start_date, end_date)
    report = build_range_report(
        db,
        start_date=start_date,
        end_date=end_date,
        threshold_price=threshold_price,
        channel=channel,
    )
    return {
        "start_date": start_date,
        "end_date": end_date,
        "channel": channel,
        "threshold_price": threshold_price,
        "markdown": render_range_markdown(report),
    }
