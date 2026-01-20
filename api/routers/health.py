# api/routers/health.py
from fastapi import APIRouter
from datetime import datetime

router = APIRouter()

@router.get("/health")
def health():
    return {
        "status": "ok",
        "server_time": datetime.now()
    }
