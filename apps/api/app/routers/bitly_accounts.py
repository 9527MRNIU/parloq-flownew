from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.deps import AdminUser, CurrentUser, DbSession
from app.models import BitlyProviderAccount
from app.schemas import BitlyAccountCreate, BitlyAccountUpdate
from app.security import encrypt_secret, secret_fingerprint, utcnow
from app.serializers import bitly_account_row
from app.services.bitly import BitlyClient, BitlyServiceError


router = APIRouter(tags=["bitly-accounts"])


def _domain(value: str) -> str:
    domain = value.lower().strip().rstrip(".")
    if not domain or "/" in domain:
        raise HTTPException(status_code=422, detail="Bitly 短域名格式不正确")
    return domain


def _account_or_404(db: DbSession, public_id: str) -> BitlyProviderAccount:
    account = db.scalar(
        select(BitlyProviderAccount).where(
            BitlyProviderAccount.public_id == public_id,
            BitlyProviderAccount.archived_at.is_(None),
        )
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Bitly 账号不存在")
    return account


def _list_accounts(db: DbSession) -> list[BitlyProviderAccount]:
    return list(
        db.scalars(
            select(BitlyProviderAccount)
            .where(BitlyProviderAccount.archived_at.is_(None))
            .order_by(BitlyProviderAccount.id)
        ).all()
    )


@router.get("/api/bitly-accounts")
def list_accounts(db: DbSession, _user: CurrentUser) -> dict:
    rows = [bitly_account_row(account) for account in _list_accounts(db)]
    return {"data": {"rows": rows, "total": len(rows)}}


@router.get("/api/direct-short-links/accounts")
def list_accounts_compat(db: DbSession, _user: CurrentUser) -> dict:
    rows = [bitly_account_row(account) for account in _list_accounts(db)]
    return {"data": {"rows": rows, "total": len(rows)}}


@router.post("/api/bitly-accounts", status_code=status.HTTP_201_CREATED)
def create_account(payload: BitlyAccountCreate, db: DbSession, _admin: AdminUser) -> dict:
    settings = get_settings()
    is_mock = settings.bitly_mock
    access_token = (payload.access_token or "").strip()
    if not access_token and not is_mock:
        raise HTTPException(status_code=422, detail="请填写 Bitly Access Token")
    if not access_token:
        access_token = f"local-mock-{uuid4().hex}"
    try:
        group_guid = payload.group_guid or BitlyClient(
            access_token, is_mock=is_mock
        ).discover_group()
    except BitlyServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    account = BitlyProviderAccount(
        public_id=f"bitly_{uuid4().hex}",
        name=payload.name,
        token_ciphertext=encrypt_secret(access_token),
        token_fingerprint=secret_fingerprint(access_token),
        token_last4=access_token[-4:],
        group_guid=group_guid,
        short_domain=_domain(payload.short_domain),
        enabled=payload.enabled,
        status="active" if payload.enabled else "disabled",
        is_mock=is_mock,
    )
    db.add(account)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Bitly 账号名称或 Token 已存在") from None
    db.refresh(account)
    return {"data": {"account": bitly_account_row(account)}}


@router.patch("/api/bitly-accounts/{public_id}")
def update_account(
    public_id: str,
    payload: BitlyAccountUpdate,
    db: DbSession,
    _admin: AdminUser,
) -> dict:
    account = _account_or_404(db, public_id)
    if payload.name is not None:
        account.name = payload.name
    if payload.short_domain is not None:
        account.short_domain = _domain(payload.short_domain)
    if payload.enabled is not None:
        account.enabled = payload.enabled
        account.status = "active" if payload.enabled else "disabled"
    if payload.group_guid is not None:
        account.group_guid = payload.group_guid
    if payload.access_token:
        token = payload.access_token.strip()
        account.token_ciphertext = encrypt_secret(token)
        account.token_fingerprint = secret_fingerprint(token)
        account.token_last4 = token[-4:]
        if payload.group_guid is None:
            try:
                account.group_guid = BitlyClient(
                    token, is_mock=account.is_mock
                ).discover_group()
            except BitlyServiceError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from None
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Bitly 账号名称或 Token 已存在") from None
    db.refresh(account)
    return {"data": {"account": bitly_account_row(account)}}


@router.delete("/api/bitly-accounts/{public_id}")
def archive_account(public_id: str, db: DbSession, _admin: AdminUser) -> dict:
    account = _account_or_404(db, public_id)
    account.enabled = False
    account.status = "archived"
    account.archived_at = utcnow()
    db.commit()
    return {"data": {"ok": True}}
