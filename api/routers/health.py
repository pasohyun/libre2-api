# api/routers/health.py
from datetime import datetime

from fastapi import APIRouter
from sqlalchemy import text

from api.database import engine

router = APIRouter()


@router.get("/health")
def health():
    return {
        "status": "ok",
        "server_time": datetime.now(),
    }


@router.get("/health/db")
def health_db():
    """
    로컬/배포에서 데이터가 안 보일 때 원인 확인용.
    인증 없음 — 비밀번호 등은 노출하지 않음.
    """
    try:
        with engine.connect() as conn:
            products_rows = int(
                conn.execute(text("SELECT COUNT(*) FROM products")).scalar() or 0
            )
            with_snapshot = int(
                conn.execute(
                    text(
                        "SELECT COUNT(*) FROM products WHERE snapshot_id IS NOT NULL"
                    )
                ).scalar()
                or 0
            )
        return {
            "db_reachable": True,
            "products_rows": products_rows,
            "rows_with_snapshot_id": with_snapshot,
            "hint": (
                "products_rows=0 이면 크롤 데이터가 없거나 다른 DB를 보고 있음. "
                "latest API는 snapshot_id가 있는 최신 스냅샷이 필요함."
            ),
        }
    except Exception as e:
        return {
            "db_reachable": False,
            "products_rows": None,
            "rows_with_snapshot_id": None,
            "error": str(e)[:500],
            "hint": (
                "MySQL이 떠 있는지, api/database.py(비 Railway) 기본 localhost·계정 또는 "
                "MYSQLHOST/MYSQLUSER/MYSQLPASSWORD/MYSQLDATABASE 환경변수를 확인."
            ),
        }
