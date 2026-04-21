from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.database import SessionLocal
from api.services.daily_alerts import (
    get_alert_config_dict,
    run_daily_alert_job,
    upsert_alert_config,
)

router = APIRouter(prefix="/alerts", tags=["alerts"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class AlertConfigUpsertBody(BaseModel):
    enabled: bool = True
    recipient_email: str = Field(..., min_length=5, max_length=255)
    threshold_price: int = Field(..., gt=0)


@router.get("/config")
def get_alert_config(db: Session = Depends(get_db)):
    return get_alert_config_dict(db)


@router.put("/config")
def put_alert_config(body: AlertConfigUpsertBody, db: Session = Depends(get_db)):
    try:
        return upsert_alert_config(
            db,
            enabled=body.enabled,
            recipient_email=body.recipient_email,
            threshold_price=body.threshold_price,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/trigger")
def trigger_daily_alert():
    try:
        return run_daily_alert_job()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"alert send failed: {str(e)}") from e
