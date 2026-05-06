# api/routers/memos.py
from __future__ import annotations

import json
from datetime import datetime
import uuid
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session

import config
from api.database import SessionLocal
from api.schemas import (
    DashboardMemoCreateGlobal,
    DashboardMemoCreateVendor,
    DashboardMemoListVendor,
    DashboardMemoOut,
)
from api.services.s3_storage import extract_object_key, generate_presigned_url, is_s3_enabled, upload_bytes

router = APIRouter(prefix="/memos", tags=["memos"])

_MAX_BODY = 20000
_MAX_SUMMARY = 500
_SCOPE_GLOBAL = "global"
_SCOPE_VENDOR = "vendor"
_MAX_IMAGE_BYTES = 10 * 1024 * 1024
_MAX_MEMO_IMAGES = 10
_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
KST = ZoneInfo("Asia/Seoul")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _to_display_image_url(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None

    if is_s3_enabled():
        key = extract_object_key(raw)
        if key:
            signed = generate_presigned_url(key, expires_in=3600)
            if signed:
                return signed
    return raw


def _parse_json_paths(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return []
        try:
            data = json.loads(s)
        except Exception:
            return []
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    return []


def _paths_from_row(row) -> list[str]:
    jp = row.get("image_paths")
    parsed = _parse_json_paths(jp)
    if parsed:
        return parsed
    ip = row.get("image_path")
    if ip and str(ip).strip():
        return [str(ip).strip()]
    return []


def _collect_create_paths(
    *,
    legacy_single: str | None,
    path_list: list[str] | None,
) -> list[str]:
    paths: list[str] = []
    if path_list:
        for p in path_list:
            s = (p or "").strip()
            if s:
                paths.append(s)
    one = (legacy_single or "").strip()
    if one:
        if one not in paths:
            paths.insert(0, one)
    # dedupe, keep order
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    if len(out) > _MAX_MEMO_IMAGES:
        raise HTTPException(
            status_code=422,
            detail=f"too many images (max {_MAX_MEMO_IMAGES})",
        )
    return out


def _row_to_out(row) -> DashboardMemoOut:
    paths = _paths_from_row(row)
    urls = [_to_display_image_url(p) or p for p in paths]
    first_path = paths[0] if paths else None
    first_url = urls[0] if urls else None
    return DashboardMemoOut(
        id=int(row["id"]),
        scope=str(row["scope"]),
        channel=row["channel"],
        vendor_label=row["vendor_label"],
        body=row["body"] or "",
        summary=row["summary"],
        image_path=first_path,
        image_url=first_url,
        image_paths=paths or None,
        image_urls=urls or None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.post("/upload-image")
async def upload_memo_image(file: UploadFile = File(...)):
    if not is_s3_enabled():
        raise HTTPException(status_code=400, detail="S3 is not enabled")

    content_type = (file.content_type or "").strip().lower()
    if content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Only jpg/png/webp/gif images are allowed")

    content = await file.read()
    size = len(content)
    if size == 0:
        raise HTTPException(status_code=422, detail="Empty file is not allowed")
    if size > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 10MB)")

    ext = (file.filename or "image").split(".")[-1].lower()
    if ext not in {"jpg", "jpeg", "png", "webp", "gif"}:
        ext = "jpg" if content_type == "image/jpeg" else content_type.split("/")[-1]

    now = datetime.now(KST)
    date_part = now.strftime("%Y%m%d")
    bucket_prefix = config.S3_PREFIX.strip("/")
    object_key = f"{bucket_prefix}/memos/{date_part}/{uuid.uuid4().hex}.{ext}"

    try:
        upload_bytes(content=content, object_key=object_key, content_type=content_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image upload failed: {e}")

    return {
        "uploaded": True,
        "image_path": object_key,
        "image_url": _to_display_image_url(object_key) or object_key,
        "content_type": content_type,
        "size": size,
    }


_MEMO_SELECT = """
            SELECT id, scope, channel, vendor_label, body, summary,
                   image_path, image_paths, created_at, updated_at
"""


@router.get("/global", response_model=list[DashboardMemoOut])
def list_global_memos(db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            f"""
            {_MEMO_SELECT.strip()}
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
    paths = _collect_create_paths(
        legacy_single=payload.image_path,
        path_list=payload.image_paths,
    )
    json_paths = json.dumps(paths, ensure_ascii=False) if paths else None
    legacy_col = paths[0] if paths else None

    r = db.execute(
        text(
            """
            INSERT INTO dashboard_memos (scope, channel, vendor_label, body, summary, image_path, image_paths)
            VALUES (:scope, NULL, NULL, :body, :summary, :image_path, :image_paths)
            """
        ),
        {
            "scope": _SCOPE_GLOBAL,
            "body": body,
            "summary": summary,
            "image_path": legacy_col,
            "image_paths": json_paths,
        },
    )
    db.commit()
    new_id = r.lastrowid
    if not new_id:
        raise HTTPException(status_code=500, detail="insert failed")
    row = db.execute(
        text(
            f"""
            {_MEMO_SELECT.strip()}
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
            f"""
            {_MEMO_SELECT.strip()}
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
    paths = _collect_create_paths(
        legacy_single=payload.image_path,
        path_list=payload.image_paths,
    )
    json_paths = json.dumps(paths, ensure_ascii=False) if paths else None
    legacy_col = paths[0] if paths else None

    r = db.execute(
        text(
            """
            INSERT INTO dashboard_memos (scope, channel, vendor_label, body, summary, image_path, image_paths)
            VALUES (:scope, :channel, :vendor_label, :body, :summary, :image_path, :image_paths)
            """
        ),
        {
            "scope": _SCOPE_VENDOR,
            "channel": ch,
            "vendor_label": vl,
            "body": body,
            "summary": summary,
            "image_path": legacy_col,
            "image_paths": json_paths,
        },
    )
    db.commit()
    new_id = r.lastrowid
    if not new_id:
        raise HTTPException(status_code=500, detail="insert failed")
    row = db.execute(
        text(
            f"""
            {_MEMO_SELECT.strip()}
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
            f"""
            {_MEMO_SELECT.strip()}
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
