# api/routers/auth_dashboard.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.auth_dashboard import create_dashboard_token, dashboard_auth_enabled, dashboard_password

router = APIRouter(prefix="/auth", tags=["auth"])


class DashboardLoginBody(BaseModel):
    password: str = Field(..., min_length=1, max_length=200)


@router.post("/dashboard/login")
def dashboard_login(body: DashboardLoginBody):
    """
    대시보드 공유 비밀번호 확인 후 JWT 발급.
    비밀번호: 환경변수 DASHBOARD_PASSWORD (기본값 DW2026)
    """
    if not dashboard_auth_enabled():
        # 인증 비활성화 시에도 토큰은 발급해 두면 프론트가 동일하게 동작
        return {
            "access_token": create_dashboard_token(),
            "token_type": "bearer",
            "auth_disabled": True,
        }
    if body.password != dashboard_password():
        raise HTTPException(status_code=401, detail="Invalid password")
    return {
        "access_token": create_dashboard_token(),
        "token_type": "bearer",
        "auth_disabled": False,
    }
