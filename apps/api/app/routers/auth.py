from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select, update

from app.config import get_settings
from app.deps import CurrentUser, DbSession
from app.models import (
    AuthSession,
    MfaLoginChallenge,
    MfaSecurityEvent,
    UserAccount,
    UserMfaCredential,
)
from app.schemas import (
    LoginRequest,
    MfaConfirmSetupRequest,
    MfaLoginVerifyRequest,
    MfaPasswordRequest,
    MfaProtectedActionRequest,
)
from app.security import (
    create_session_token,
    decrypt_secret,
    encrypt_secret,
    secret_fingerprint,
    utcnow,
    verify_password,
)
from app.serializers import user_row
from app.services.login_security import (
    LoginSecurityUnavailable,
    clear_user_failures,
    record_failure,
    state as login_security_state,
    verify_turnstile,
)
from app.services.mfa import (
    consume_recovery_code,
    generate_recovery_codes,
    generate_totp_secret,
    otpauth_uri,
    record_event,
    recovery_code_hashes,
    source_ip_hash,
    verify_totp,
)
from app.snowflake import new_public_id


router = APIRouter(prefix="/api/auth", tags=["auth"])
MFA_CHALLENGE_TTL_SECONDS = 300
MFA_CHALLENGE_MAX_FAILURES = 5
MFA_FAILURE_WINDOW_SECONDS = 600
MFA_FAILURE_LIMIT = 10


def _source_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _security_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="登录安全服务暂时不可用，请稍后重试",
    )


def _complete_login(response: Response, db: DbSession, user: UserAccount) -> dict:
    settings = get_settings()
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
        "mfaRequired": False,
        "token": token,
        "tokenType": "bearer",
        "expiresAt": expires_at.isoformat(),
        "user": user_row(user),
    }


def _revoke_other_sessions(db: DbSession, user_id: int, current_session_id: int) -> None:
    db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.id != current_session_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow())
    )


def _enabled_mfa(user: UserAccount) -> UserMfaCredential | None:
    credential = user.mfa_credential
    if credential is None or credential.enabled_at is None:
        return None
    return credential


def _require_current_password(user: UserAccount, password: str) -> None:
    if not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="当前密码错误")


def _recent_mfa_failure_count(db: DbSession, user_id: int) -> int:
    since = utcnow() - timedelta(seconds=MFA_FAILURE_WINDOW_SECONDS)
    return int(
        db.scalar(
            select(func.count()).select_from(MfaSecurityEvent).where(
                MfaSecurityEvent.user_id == user_id,
                MfaSecurityEvent.event_type == "login_challenge_failed",
                MfaSecurityEvent.created_at > since,
            )
        )
        or 0
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
    if not user.is_active or not user.group.enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已停用")
    try:
        clear_user_failures(payload.username, source_ip)
    except LoginSecurityUnavailable:
        if settings.environment.lower() in {"production", "prod"}:
            raise _security_unavailable() from None
    credential = _enabled_mfa(user)
    if credential is not None:
        if _recent_mfa_failure_count(db, user.id) >= MFA_FAILURE_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="二步验证失败次数过多，请稍后重试",
                headers={"Retry-After": str(MFA_FAILURE_WINDOW_SECONDS)},
            )
        now = utcnow()
        db.execute(
            update(MfaLoginChallenge)
            .where(
                MfaLoginChallenge.user_id == user.id,
                MfaLoginChallenge.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )
        challenge_token = secrets.token_urlsafe(48)
        expires_at = now + timedelta(seconds=MFA_CHALLENGE_TTL_SECONDS)
        db.add(
            MfaLoginChallenge(
                token_hash=secret_fingerprint(challenge_token),
                user_id=user.id,
                source_ip_hash=source_ip_hash(source_ip),
                expires_at=expires_at,
            )
        )
        record_event(
            db,
            "login_challenge_created",
            user_id=user.id,
            source_ip=source_ip,
        )
        db.commit()
        return {
            "data": {
                "mfaRequired": True,
                "challengeToken": challenge_token,
                "expiresAt": expires_at.isoformat(),
            }
        }
    data = _complete_login(response, db, user)
    db.commit()
    return {"data": data}


@router.post("/mfa/login/verify")
def verify_mfa_login(
    payload: MfaLoginVerifyRequest,
    request: Request,
    response: Response,
    db: DbSession,
) -> dict:
    now = utcnow()
    challenge = db.scalar(
        select(MfaLoginChallenge)
        .where(
            MfaLoginChallenge.token_hash == secret_fingerprint(payload.challenge_token),
            MfaLoginChallenge.consumed_at.is_(None),
            MfaLoginChallenge.expires_at > now,
            MfaLoginChallenge.failure_count < MFA_CHALLENGE_MAX_FAILURES,
        )
        .with_for_update()
    )
    if challenge is None:
        raise HTTPException(status_code=401, detail="验证请求已失效，请重新登录")
    user = db.get(UserAccount, challenge.user_id)
    credential = user.mfa_credential if user else None
    if (
        user is None
        or not user.is_active
        or not user.group.enabled
        or credential is None
        or credential.enabled_at is None
    ):
        challenge.consumed_at = now
        db.commit()
        raise HTTPException(status_code=401, detail="验证请求已失效，请重新登录")

    source_ip = _source_ip(request)
    method: str | None = None
    try:
        secret = decrypt_secret(credential.secret_ciphertext)
    except ValueError:
        challenge.consumed_at = now
        record_event(
            db,
            "login_challenge_unavailable",
            user_id=user.id,
            source_ip=source_ip,
        )
        db.commit()
        raise HTTPException(status_code=503, detail="二步验证配置不可用，请联系管理员") from None
    matched_counter = verify_totp(
        secret,
        payload.code,
        last_used_counter=credential.last_used_counter,
    )
    if matched_counter is not None:
        credential.last_used_counter = matched_counter
        method = "totp"
    else:
        recovered, remaining_hashes = consume_recovery_code(
            credential.recovery_code_hashes, payload.code
        )
        if recovered:
            credential.recovery_code_hashes = remaining_hashes
            method = "recovery_code"

    if method is None:
        challenge.failure_count += 1
        if challenge.failure_count >= MFA_CHALLENGE_MAX_FAILURES:
            challenge.consumed_at = now
        record_event(
            db,
            "login_challenge_failed",
            user_id=user.id,
            source_ip=source_ip,
            details={"failureCount": challenge.failure_count},
        )
        db.commit()
        raise HTTPException(status_code=401, detail="验证码或恢复码错误")

    challenge.consumed_at = now
    record_event(
        db,
        "login_challenge_succeeded",
        user_id=user.id,
        source_ip=source_ip,
        details={
            "method": method,
            "recoveryCodesRemaining": len(credential.recovery_code_hashes),
        },
    )
    data = _complete_login(response, db, user)
    db.commit()
    return {"data": data}


@router.get("/mfa/status")
def mfa_status(user: CurrentUser) -> dict:
    credential = user.mfa_credential
    enabled = bool(credential and credential.enabled_at is not None)
    return {
        "data": {
            "enabled": enabled,
            "enabledAt": credential.enabled_at.isoformat() if enabled else None,
            "recoveryCodesRemaining": len(credential.recovery_code_hashes) if enabled else 0,
            "pendingSetup": bool(credential and credential.enabled_at is None),
        }
    }


@router.post("/mfa/setup")
def start_mfa_setup(
    payload: MfaPasswordRequest,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> dict:
    _require_current_password(user, payload.current_password)
    if _enabled_mfa(user) is not None:
        raise HTTPException(status_code=409, detail="二步验证已经开启")
    secret = generate_totp_secret()
    credential = user.mfa_credential
    if credential is None:
        credential = UserMfaCredential(
            user_id=user.id,
            secret_ciphertext=encrypt_secret(secret),
            recovery_code_hashes=[],
        )
        db.add(credential)
    else:
        credential.secret_ciphertext = encrypt_secret(secret)
        credential.recovery_code_hashes = []
        credential.enabled_at = None
        credential.last_used_counter = None
    record_event(
        db,
        "setup_started",
        user_id=user.id,
        actor_user_id=user.id,
        source_ip=_source_ip(request),
    )
    db.commit()
    return {
        "data": {
            "secret": secret,
            "otpauthUri": otpauth_uri(secret, user.username),
        }
    }


@router.post("/mfa/setup/confirm")
def confirm_mfa_setup(
    payload: MfaConfirmSetupRequest,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> dict:
    credential = user.mfa_credential
    if credential is None or credential.enabled_at is not None:
        raise HTTPException(status_code=409, detail="请先开始二步验证设置")
    try:
        secret = decrypt_secret(credential.secret_ciphertext)
    except ValueError:
        raise HTTPException(status_code=503, detail="二步验证配置不可用，请重新设置") from None
    matched_counter = verify_totp(secret, payload.code)
    if matched_counter is None:
        record_event(
            db,
            "setup_confirmation_failed",
            user_id=user.id,
            actor_user_id=user.id,
            source_ip=_source_ip(request),
        )
        db.commit()
        raise HTTPException(status_code=401, detail="验证码错误")
    codes = generate_recovery_codes()
    credential.recovery_code_hashes = recovery_code_hashes(codes)
    credential.enabled_at = utcnow()
    credential.last_used_counter = matched_counter
    _revoke_other_sessions(db, user.id, request.state.auth_session.id)
    record_event(
        db,
        "enabled",
        user_id=user.id,
        actor_user_id=user.id,
        source_ip=_source_ip(request),
    )
    db.commit()
    return {"data": {"enabled": True, "recoveryCodes": codes}}


@router.post("/mfa/recovery-codes")
def regenerate_mfa_recovery_codes(
    payload: MfaProtectedActionRequest,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> dict:
    _require_current_password(user, payload.current_password)
    credential = _enabled_mfa(user)
    if credential is None:
        raise HTTPException(status_code=409, detail="二步验证尚未开启")
    try:
        secret = decrypt_secret(credential.secret_ciphertext)
    except ValueError:
        raise HTTPException(status_code=503, detail="二步验证配置不可用，请联系管理员") from None
    matched_counter = verify_totp(
        secret, payload.code, last_used_counter=credential.last_used_counter
    )
    if matched_counter is None:
        raise HTTPException(status_code=401, detail="验证码错误或已使用")
    codes = generate_recovery_codes()
    credential.last_used_counter = matched_counter
    credential.recovery_code_hashes = recovery_code_hashes(codes)
    record_event(
        db,
        "recovery_codes_regenerated",
        user_id=user.id,
        actor_user_id=user.id,
        source_ip=_source_ip(request),
    )
    db.commit()
    return {"data": {"recoveryCodes": codes}}


@router.post("/mfa/disable")
def disable_mfa(
    payload: MfaProtectedActionRequest,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> dict:
    _require_current_password(user, payload.current_password)
    credential = _enabled_mfa(user)
    if credential is None:
        raise HTTPException(status_code=409, detail="二步验证尚未开启")
    try:
        secret = decrypt_secret(credential.secret_ciphertext)
    except ValueError:
        raise HTTPException(status_code=503, detail="二步验证配置不可用，请联系管理员") from None
    matched_counter = verify_totp(
        secret, payload.code, last_used_counter=credential.last_used_counter
    )
    if matched_counter is None:
        raise HTTPException(status_code=401, detail="验证码错误或已使用")
    _revoke_other_sessions(db, user.id, request.state.auth_session.id)
    db.delete(credential)
    record_event(
        db,
        "disabled",
        user_id=user.id,
        actor_user_id=user.id,
        source_ip=_source_ip(request),
    )
    db.commit()
    return {"data": {"ok": True}}


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
