from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import select

from app.config import get_settings
from app.deps import CurrentUser, DbSession
from app.models import AuthSession, UserAccount
from app.schemas import LoginRequest
from app.security import create_session_token, utcnow, verify_password
from app.serializers import user_row
from app.services.login_security import (
    LoginSecurityUnavailable,
    clear_user_failures,
    record_failure,
    state as login_security_state,
    verify_turnstile,
)
from app.snowflake import new_public_id


router = APIRouter(prefix="/api/auth", tags=["auth"])


def _source_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _security_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="登录安全服务暂时不可用，请稍后重试",
    )


@router.get("/security")
def login_security(
    request: Request,
    username: str = Query(default="", max_length=80),
) -> dict:
    settings = get_settings()
    try:
        security = login_security_state(username, _source_ip(request))
    except LoginSecurityUnavailable:
        if settings.environment.lower() in {"production", "prod"}:
            raise _security_unavailable() from None
        security = None
    return {
        "data": {
            "turnstileEnabled": settings.turnstile_enabled,
            "turnstileRequired": bool(security and security.turnstile_required),
            "turnstileSiteKey": settings.turnstile_site_key if settings.turnstile_enabled else "",
            "lockWindowSeconds": settings.login_lock_window_seconds,
            "lockSeconds": settings.login_lock_seconds,
            "userFailureLimit": settings.login_user_failure_limit,
            "ipFailureLimit": settings.login_ip_failure_limit,
            "locked": bool(security and security.locked),
            "retryAfterSeconds": security.retry_after_seconds if security else 0,
        }
    }


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response, db: DbSession) -> dict:
    settings = get_settings()
    source_ip = _source_ip(request)
    try:
        security = login_security_state(payload.username, source_ip)
    except LoginSecurityUnavailable:
        if settings.environment.lower() in {"production", "prod"}:
            raise _security_unavailable() from None
        security = None
    if security and security.locked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="登录失败次数过多，请稍后重试",
            headers={"Retry-After": str(max(security.retry_after_seconds, 1))},
        )
    if security and security.turnstile_required and not verify_turnstile(
        payload.turnstile_token, source_ip
    ):
        raise HTTPException(status_code=400, detail="请完成人机验证")
    user = db.scalar(select(UserAccount).where(UserAccount.username == payload.username))
    if user is None or not verify_password(payload.password, user.password_hash):
        try:
            failure = record_failure(payload.username, source_ip)
        except LoginSecurityUnavailable:
            if settings.environment.lower() in {"production", "prod"}:
                raise _security_unavailable() from None
            failure = None
        if failure and failure.locked:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="登录失败次数过多，请稍后重试",
                headers={"Retry-After": str(settings.login_lock_seconds)},
            )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已停用")
    try:
        clear_user_failures(payload.username, source_ip)
    except LoginSecurityUnavailable:
        if settings.environment.lower() in {"production", "prod"}:
            raise _security_unavailable() from None
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
