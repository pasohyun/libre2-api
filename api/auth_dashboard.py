# api/auth_dashboard.py
"""대시보드 공유 비밀번호 + JWT (메인 화면용)."""
from __future__ import annotations

import os
import warnings

import jwt
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)


def dashboard_auth_enabled() -> bool:
    v = (os.getenv("DASHBOARD_AUTH_ENABLED") or "true").strip().lower()
    return v not in ("0", "false", "no", "off")


def dashboard_password() -> str:
    return os.getenv("DASHBOARD_PASSWORD") or "DW2026"


def jwt_secret() -> str:
    s = (os.getenv("JWT_SECRET") or "").strip()
    if not s:
        warnings.warn(
            "JWT_SECRET is not set; using insecure dev default. Set JWT_SECRET in production.",
            stacklevel=2,
        )
        return "dev-insecure-jwt-secret-change-me"
    return s


def create_dashboard_token() -> str:
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=7)
    payload = {
        "sub": "dashboard",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, jwt_secret(), algorithm="HS256")


def require_dashboard_auth(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> None:
    if not dashboard_auth_enabled():
        return
    if credentials is None or (credentials.scheme or "").lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        decoded = jwt.decode(
            credentials.credentials,
            jwt_secret(),
            algorithms=["HS256"],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None
    if decoded.get("sub") != "dashboard":
        raise HTTPException(status_code=401, detail="Invalid or expired token")
