# api/routers/memos.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.database import SessionLocal
from api.schemas import (
    DashboardMemoCreateGlobal,
    DashboardMemoCreateVendor,
    DashboardMemoListVendor,
    DashboardMemoOut,
)

router = APIRouter(prefix="/memos", tags=["memos"])

_MAX_BODY = 20000
_MAX_SUMMARY = 500
_SCOPE_GLOBAL = "global"
_SCOPE_VENDOR = "vendor"


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _row_to_out(row) -> DashboardMemoOut:
    return DashboardMemoOut(
        id=int(row["id"]),
        scope=str(row["scope"]),
        channel=row["channel"],
        vendor_label=row["vendor_label"],
        body=row["body"] or "",
        summary=row["summary"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get("/global", response_model=list[DashboardMemoOut])
def list_global_memos(db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            """
            SELECT id, scope, channel, vendor_label, body, summary, created_at, updated_at
            FROM dashboard_memos
            WHERE scope = :scope
            ORDER BY created_at DESC
            LIMIT 500
            """
        ),
        {"scope": _SCOPE_GLOBAL},
    ).mappings().all()
    return [_row_to_out(r) for r in rows]


@router.post("/global", response_model=DashboardMemoOut)
def create_global_memo(payload: DashboardMemoCreateGlobal, db: Session = Depends(get_db)):
    body = (payload.body or "").strip()
    if not body:
        raise HTTPException(status_code=422, detail="body is required")
    if len(body) > _MAX_BODY:
        raise HTTPException(status_code=422, detail="body too long")
    summary = (payload.summary or "").strip() or None
    if summary and len(summary) > _MAX_SUMMARY:
        raise HTTPException(status_code=422, detail="summary too long")

    r = db.execute(
        text(
            """
            INSERT INTO dashboard_memos (scope, channel, vendor_label, body, summary)
            VALUES (:scope, NULL, NULL, :body, :summary)
            """
        ),
        {"scope": _SCOPE_GLOBAL, "body": body, "summary": summary},
    )
    db.commit()
    new_id = r.lastrowid
    if not new_id:
        raise HTTPException(status_code=500, detail="insert failed")
    row = db.execute(
        text(
            """
            SELECT id, scope, channel, vendor_label, body, summary, created_at, updated_at
            FROM dashboard_memos WHERE id = :id
            """
        ),
        {"id": new_id},
    ).mappings().first()
    return _row_to_out(row)


@router.get("/vendor", response_model=list[DashboardMemoOut])
def list_vendor_memos(
    channel: str = Query(..., description="naver | coupang | …"),
    vendor_label: str = Query(..., description="타임라인 API와 동일한 판매처 키(원문)"),
    db: Session = Depends(get_db),
):
    ch = (channel or "").strip()
    vl = (vendor_label or "").strip()
    if not ch or not vl:
        raise HTTPException(status_code=422, detail="channel and vendor_label required")

    rows = db.execute(
        text(
            """
            SELECT id, scope, channel, vendor_label, body, summary, created_at, updated_at
            FROM dashboard_memos
            WHERE scope = :scope AND channel = :channel AND vendor_label = :vendor_label
            ORDER BY created_at DESC
            LIMIT 200
            """
        ),
        {"scope": _SCOPE_VENDOR, "channel": ch, "vendor_label": vl},
    ).mappings().all()
    return [_row_to_out(r) for r in rows]


@router.post("/vendor", response_model=DashboardMemoOut)
def create_vendor_memo(payload: DashboardMemoCreateVendor, db: Session = Depends(get_db)):
    body = (payload.body or "").strip()
    ch = (payload.channel or "").strip()
    vl = (payload.vendor_label or "").strip()
    if not body:
        raise HTTPException(status_code=422, detail="body is required")
    if not ch or not vl:
        raise HTTPException(status_code=422, detail="channel and vendor_label required")
    if len(body) > _MAX_BODY:
        raise HTTPException(status_code=422, detail="body too long")
    summary = (payload.summary or "").strip() or None
    if summary and len(summary) > _MAX_SUMMARY:
        raise HTTPException(status_code=422, detail="summary too long")

    r = db.execute(
        text(
            """
            INSERT INTO dashboard_memos (scope, channel, vendor_label, body, summary)
            VALUES (:scope, :channel, :vendor_label, :body, :summary)
            """
        ),
        {
            "scope": _SCOPE_VENDOR,
            "channel": ch,
            "vendor_label": vl,
            "body": body,
            "summary": summary,
        },
    )
    db.commit()
    new_id = r.lastrowid
    if not new_id:
        raise HTTPException(status_code=500, detail="insert failed")
    row = db.execute(
        text(
            """
            SELECT id, scope, channel, vendor_label, body, summary, created_at, updated_at
            FROM dashboard_memos WHERE id = :id
            """
        ),
        {"id": new_id},
    ).mappings().first()
    return _row_to_out(row)


@router.get("/vendors/aggregate", response_model=DashboardMemoListVendor)
def list_all_vendor_memos(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    total = db.execute(
        text("SELECT COUNT(*) AS c FROM dashboard_memos WHERE scope = :scope"),
        {"scope": _SCOPE_VENDOR},
    ).mappings().first()
    count = int(total["c"] or 0) if total else 0

    rows = db.execute(
        text(
            """
            SELECT id, scope, channel, vendor_label, body, summary, created_at, updated_at
            FROM dashboard_memos
            WHERE scope = :scope
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        {"scope": _SCOPE_VENDOR, "limit": limit, "offset": offset},
    ).mappings().all()
    return DashboardMemoListVendor(count=count, items=[_row_to_out(r) for r in rows])


@router.delete("/{memo_id}")
def delete_memo(memo_id: int, db: Session = Depends(get_db)):
    r = db.execute(text("DELETE FROM dashboard_memos WHERE id = :id"), {"id": memo_id})
    db.commit()
    if r.rowcount == 0:
        raise HTTPException(status_code=404, detail="memo not found")
    return {"deleted": True, "id": memo_id}
