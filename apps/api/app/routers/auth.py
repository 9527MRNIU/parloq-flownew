from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from app.config import get_settings
from app.deps import CurrentUser, DbSession
from app.models import AuthSession, UserAccount
from app.schemas import LoginRequest
from app.security import create_session_token, utcnow, verify_password
from app.serializers import user_row
from app.snowflake import new_public_id


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(payload: LoginRequest, response: Response, db: DbSession) -> dict:
    user = db.scalar(select(UserAccount).where(UserAccount.username == payload.username))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已停用")
    token, token_hash, expires_at = create_session_token()
    db.add(
        AuthSession(
            public_id=new_public_id("ses"),
            token_hash=token_hash,
            user_id=user.id,
            expires_at=expires_at,
        )
    )
    user.last_login_at = utcnow()
    db.commit()
    settings = get_settings()
    response.set_cookie(
        settings.auth_cookie_name,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.auth_session_hours * 3600,
        path="/",
    )
    return {
        "data": {
            "token": token,
            "tokenType": "bearer",
            "expiresAt": expires_at.isoformat(),
            "user": user_row(user),
        }
    }


@router.get("/me")
def me(user: CurrentUser) -> dict:
    return {"data": {"user": user_row(user)}}


@router.post("/logout")
def logout(request: Request, response: Response, db: DbSession, _user: CurrentUser) -> dict:
    auth_session = request.state.auth_session
    auth_session.revoked_at = utcnow()
    db.commit()
    response.delete_cookie(get_settings().auth_cookie_name, path="/")
    return {"data": {"ok": True}}
