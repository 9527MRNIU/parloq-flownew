from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, or_, select

from app.deps import CurrentUser, DbSession
from app.entity_ids import identifier_filter
from app.models import BitlyProviderAccount, DirectShortLink
from app.schemas import (
    DirectShortLinkClickSync,
    DirectShortLinkCreate,
    DirectShortLinkUpdate,
)
from app.security import decrypt_secret, utcnow
from app.serializers import direct_short_link_row
from app.services.bitly import BitlyClient, BitlyServiceError
from app.snowflake import new_public_id


router = APIRouter(prefix="/api/direct-short-links", tags=["direct-short-links"])


def _accounts_for_create(
    db: DbSession,
    identifier: str | None,
) -> list[BitlyProviderAccount]:
    now = utcnow()
    statement = select(BitlyProviderAccount).where(
        BitlyProviderAccount.enabled.is_(True),
        BitlyProviderAccount.status == "active",
        or_(
            BitlyProviderAccount.cooldown_until.is_(None),
            BitlyProviderAccount.cooldown_until <= now,
        ),
    )
    if identifier:
        statement = statement.where(
            identifier_filter(BitlyProviderAccount, identifier)
        )
    return list(
        db.scalars(
            statement.order_by(
                BitlyProviderAccount.last_used_at.asc().nullsfirst(),
                BitlyProviderAccount.id,
            )
        ).all()
    )


def _link_or_404(db: DbSession, identifier: str, user) -> DirectShortLink:
    statement = select(DirectShortLink).where(
        identifier_filter(DirectShortLink, identifier),
    )
    if user.role != "admin":
        statement = statement.where(DirectShortLink.created_by == user.id)
    link = db.scalar(statement)
    if link is None:
        raise HTTPException(status_code=404, detail="直接短链不存在")
    return link


def _client(account: BitlyProviderAccount) -> BitlyClient:
    try:
        token = decrypt_secret(account.token_ciphertext)
    except ValueError:
        raise BitlyServiceError(
            "Bitly Token 无法解密，请重新保存",
            category="invalid",
        ) from None
    return BitlyClient(token, is_mock=account.is_mock)


def _record_account_failure(
    db: DbSession,
    account: BitlyProviderAccount,
    error: BitlyServiceError,
) -> None:
    account.last_error = str(error)[:2000]
    if error.category == "invalid":
        account.status = "invalid"
        account.cooldown_until = None
    elif error.category == "quota_exhausted":
        account.status = "exhausted"
        account.cooldown_until = None
    elif error.category == "configuration":
        account.status = "error"
        account.cooldown_until = None
    elif error.category in {"temporary", "rate_limited"}:
        cooldown = min(max(int(error.retry_after or 60), 60), 3600)
        account.cooldown_until = utcnow() + timedelta(seconds=cooldown)
    db.commit()


def _record_account_success(
    db: DbSession,
    account: BitlyProviderAccount,
) -> None:
    account.last_error = None
    account.cooldown_until = None
    account.last_used_at = utcnow()
    account.status = "active" if account.enabled else "disabled"
    db.commit()


@router.get("")
def list_links(
    db: DbSession,
    current_user: CurrentUser,
    keyword: str | None = None,
    link_status: str | None = Query(default=None, alias="status"),
    provider_account_id: str | None = Query(default=None, alias="providerAccountId"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
) -> dict:
    statement = select(DirectShortLink)
    if current_user.role != "admin":
        statement = statement.where(DirectShortLink.created_by == current_user.id)
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        statement = statement.where(
            or_(
                DirectShortLink.title.ilike(pattern),
                DirectShortLink.short_url.ilike(pattern),
                DirectShortLink.target_url.ilike(pattern),
            )
        )
    if link_status and link_status != "all":
        statement = statement.where(DirectShortLink.status == link_status)
    if provider_account_id:
        statement = statement.join(BitlyProviderAccount).where(
            identifier_filter(BitlyProviderAccount, provider_account_id)
        )
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    links = db.scalars(
        statement.order_by(DirectShortLink.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "data": {
            "rows": [direct_short_link_row(link) for link in links],
            "total": int(total),
            "page": page,
            "pageSize": page_size,
        }
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_link(
    payload: DirectShortLinkCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    accounts = _accounts_for_create(db, payload.provider_account_id)
    if not accounts:
        raise HTTPException(status_code=409, detail="没有可用的 Bitly 账号")
    target_url = str(payload.target_url)
    errors: list[str] = []
    for account in accounts:
        try:
            result = _client(account).create_bitlink(
                target_url=target_url,
                title=payload.title,
                group_guid=account.group_guid,
                domain=account.short_domain,
            )
            bitlink_id = str(result.get("id") or "").strip()
            short_url = str(result.get("link") or "").strip()
            if not bitlink_id or not short_url:
                raise BitlyServiceError(
                    "Bitly 未返回有效短链",
                    category="temporary",
                )
        except BitlyServiceError as exc:
            errors.append(str(exc))
            _record_account_failure(db, account, exc)
            continue

        _record_account_success(db, account)
        link = DirectShortLink(
            public_id=new_public_id("dsl"),
            title=payload.title,
            target_url=target_url,
            bitlink_id=bitlink_id,
            short_url=short_url,
            provider_account_id=account.id,
            enabled=True,
            status="active",
            click_count=0,
            created_by=current_user.id,
        )
        db.add(link)
        db.commit()
        db.refresh(link)
        return {"data": {"link": direct_short_link_row(link)}}

    detail = errors[-1] if errors else "Bitly 账号池没有返回可用账号"
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"所有可用 Bitly 账号均创建失败：{detail}",
    )


@router.post("/sync-clicks")
def sync_clicks(
    payload: DirectShortLinkClickSync,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    updated = 0
    failures: list[dict[str, str]] = []
    seen: set[str] = set()
    for identifier in payload.link_ids:
        if identifier in seen:
            continue
        seen.add(identifier)
        try:
            link = _link_or_404(db, identifier, current_user)
            summary = _client(link.provider_account).click_summary(link.bitlink_id)
            click_count = max(int(summary.get("total_clicks") or 0), 0)
        except (TypeError, ValueError):
            failures.append({"id": identifier, "message": "Bitly 点击统计格式不正确"})
            continue
        except (HTTPException, BitlyServiceError) as exc:
            message = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
            failures.append({"id": identifier, "message": message[:300]})
            continue
        link.click_count = click_count
        link.clicks_synced_at = utcnow()
        link.last_error = None
        db.commit()
        updated += 1
    return {
        "data": {
            "updated": updated,
            "failed": len(failures),
            "failures": failures,
        }
    }


@router.patch("/{link_id}")
def update_link(
    link_id: str,
    payload: DirectShortLinkUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    link = _link_or_404(db, link_id, current_user)
    target_url = str(payload.target_url) if payload.target_url is not None else None
    title = payload.title if "title" in payload.model_fields_set else None
    try:
        result = _client(link.provider_account).update_bitlink(
            link.bitlink_id,
            target_url=target_url,
            title=(title or "") if "title" in payload.model_fields_set else None,
            archived=(not payload.enabled) if payload.enabled is not None else None,
        )
    except BitlyServiceError as exc:
        link.last_error = str(exc)[:2000]
        _record_account_failure(db, link.provider_account, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from None
    _record_account_success(db, link.provider_account)
    if target_url is not None:
        link.target_url = target_url
    if "title" in payload.model_fields_set:
        link.title = title
    if payload.enabled is not None:
        link.enabled = payload.enabled
        link.status = "active" if payload.enabled else "disabled"
    link.short_url = str(result.get("link") or link.short_url)
    link.last_error = None
    db.commit()
    db.refresh(link)
    return {"data": {"link": direct_short_link_row(link)}}


@router.delete("/{link_id}")
def delete_link(link_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    link = _link_or_404(db, link_id, current_user)
    db.delete(link)
    db.commit()
    return {"data": {"ok": True}}
