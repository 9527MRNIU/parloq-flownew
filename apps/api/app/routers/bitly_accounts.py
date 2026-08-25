from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.deps import AdminUser, CurrentUser, DbSession
from app.entity_ids import identifier_filter
from app.models import BitlyProviderAccount, DirectShortLink
from app.schemas import BitlyAccountCreate, BitlyAccountUpdate
from app.security import encrypt_secret, secret_fingerprint
from app.serializers import bitly_account_row
from app.services.bitly import BitlyClient, BitlyServiceError
from app.snowflake import new_public_id


router = APIRouter(tags=["bitly-accounts"])


def _domain(value: str) -> str:
    domain = value.lower().strip().rstrip(".")
    if not domain or "/" in domain or " " in domain:
        raise HTTPException(status_code=422, detail="Bitly 短域名格式不正确")
    return domain


def _account_or_404(db: DbSession, identifier: str) -> BitlyProviderAccount:
    account = db.scalar(
        select(BitlyProviderAccount).where(
            identifier_filter(BitlyProviderAccount, identifier),
        )
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Bitly 账号不存在")
    return account


def _list_accounts(db: DbSession) -> list[BitlyProviderAccount]:
    return list(
        db.scalars(
            select(BitlyProviderAccount).order_by(BitlyProviderAccount.id)
        ).all()
    )


def _unique_name(
    db: DbSession,
    value: str,
    *,
    exclude_id: int | None = None,
) -> str:
    base = value.strip()[:120] or "Bitly 账号"
    candidate = base
    suffix = 2
    while db.scalar(
        select(BitlyProviderAccount.id).where(
            BitlyProviderAccount.name == candidate,
            *(
                (BitlyProviderAccount.id != exclude_id,)
                if exclude_id is not None
                else ()
            ),
        )
    ) is not None:
        marker = f" ({suffix})"
        candidate = f"{base[: 120 - len(marker)]}{marker}"
        suffix += 1
    return candidate


def _raise_service_error(error: BitlyServiceError) -> NoReturn:
    status_code = (
        status.HTTP_422_UNPROCESSABLE_ENTITY
        if error.category in {"invalid", "configuration"}
        else status.HTTP_502_BAD_GATEWAY
    )
    raise HTTPException(status_code=status_code, detail=str(error)) from None


def _list_accounts_page(
    db: DbSession,
    *,
    keyword: str | None,
    page: int,
    page_size: int,
) -> dict:
    statement = select(BitlyProviderAccount)
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        statement = statement.where(
            or_(
                BitlyProviderAccount.name.ilike(pattern),
                BitlyProviderAccount.short_domain.ilike(pattern),
                BitlyProviderAccount.status.ilike(pattern),
            )
        )
    total = int(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    accounts = db.scalars(
        statement.order_by(BitlyProviderAccount.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "data": {
            "rows": [bitly_account_row(account) for account in accounts],
            "total": total,
            "page": page,
            "pageSize": page_size,
        }
    }


@router.get("/api/bitly-accounts")
def list_accounts(
    db: DbSession,
    _user: CurrentUser,
    keyword: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
) -> dict:
    return _list_accounts_page(
        db,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )


@router.get("/api/direct-short-links/accounts")
def list_accounts_compat(
    db: DbSession,
    _user: CurrentUser,
    keyword: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
) -> dict:
    return _list_accounts_page(
        db,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )


@router.get("/api/bitly-accounts/options")
@router.get("/api/direct-short-links/accounts/options")
def list_account_options(db: DbSession, _user: CurrentUser) -> dict:
    rows = [bitly_account_row(account) for account in _list_accounts(db)]
    return {"data": {"rows": rows, "total": len(rows)}}


@router.post("/api/bitly-accounts", status_code=status.HTTP_201_CREATED)
def create_account(payload: BitlyAccountCreate, db: DbSession, _admin: AdminUser) -> dict:
    settings = get_settings()
    access_token = payload.access_token.strip()
    fingerprint = secret_fingerprint(access_token)
    if db.scalar(
        select(BitlyProviderAccount.id).where(
            BitlyProviderAccount.token_fingerprint == fingerprint
        )
    ) is not None:
        raise HTTPException(status_code=409, detail="该 Bitly Token 已存在")
    try:
        discovered = BitlyClient(
            access_token,
            is_mock=settings.bitly_mock,
        ).discover_account()
    except BitlyServiceError as exc:
        _raise_service_error(exc)
    account = BitlyProviderAccount(
        public_id=new_public_id("bitly"),
        name=_unique_name(db, discovered["name"]),
        token_ciphertext=encrypt_secret(access_token),
        token_fingerprint=fingerprint,
        token_last4=access_token[-4:],
        group_guid=discovered["groupGuid"],
        short_domain=_domain(discovered["shortDomain"]),
        enabled=True,
        status="active",
        is_mock=settings.bitly_mock,
        last_error=None,
    )
    db.add(account)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Bitly 账号或 Token 已存在") from None
    db.refresh(account)
    return {"data": {"account": bitly_account_row(account)}}


@router.patch("/api/bitly-accounts/{account_id}")
def update_account(
    account_id: str,
    payload: BitlyAccountUpdate,
    db: DbSession,
    _admin: AdminUser,
) -> dict:
    account = _account_or_404(db, account_id)
    if payload.access_token is not None:
        token = payload.access_token.strip()
        fingerprint = secret_fingerprint(token)
        duplicate = db.scalar(
            select(BitlyProviderAccount.id).where(
                BitlyProviderAccount.token_fingerprint == fingerprint,
                BitlyProviderAccount.id != account.id,
            )
        )
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="该 Bitly Token 已存在")
        try:
            discovered = BitlyClient(
                token,
                is_mock=account.is_mock,
            ).discover_account()
        except BitlyServiceError as exc:
            _raise_service_error(exc)
        account.token_ciphertext = encrypt_secret(token)
        account.token_fingerprint = fingerprint
        account.token_last4 = token[-4:]
        account.group_guid = discovered["groupGuid"]
        account.short_domain = _domain(discovered["shortDomain"])
        if payload.name is None:
            account.name = _unique_name(
                db,
                discovered["name"],
                exclude_id=account.id,
            )
        account.status = "active" if account.enabled else "disabled"
        account.cooldown_until = None
        account.last_error = None
    if payload.name is not None:
        account.name = _unique_name(db, payload.name, exclude_id=account.id)
    if payload.enabled is not None:
        account.enabled = payload.enabled
        if not payload.enabled:
            account.status = "disabled"
        elif account.status in {"disabled", "error", "exhausted"}:
            account.status = "active"
            account.cooldown_until = None
            account.last_error = None
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Bitly 账号或 Token 已存在") from None
    db.refresh(account)
    return {"data": {"account": bitly_account_row(account)}}


@router.delete("/api/bitly-accounts/{account_id}")
def delete_account(account_id: str, db: DbSession, _admin: AdminUser) -> dict:
    account = _account_or_404(db, account_id)
    link_count = db.scalar(
        select(func.count(DirectShortLink.id)).where(
            DirectShortLink.provider_account_id == account.id
        )
    ) or 0
    if link_count:
        raise HTTPException(
            status_code=409,
            detail=f"该账号仍关联 {link_count} 条直接短链，请停用账号而不是删除",
        )
    db.delete(account)
    db.commit()
    return {"data": {"ok": True}}
