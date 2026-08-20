from __future__ import annotations


from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, or_, select

from app.deps import CurrentUser, DbSession
from app.entity_ids import identifier_filter
from app.snowflake import new_public_id

from app.models import BitlyProviderAccount, DirectShortLink
from app.schemas import DirectShortLinkCreate, DirectShortLinkUpdate
from app.security import decrypt_secret
from app.serializers import direct_short_link_row
from app.services.bitly import BitlyClient, BitlyServiceError


router = APIRouter(prefix="/api/direct-short-links", tags=["direct-short-links"])


def _account_for_create(db: DbSession, identifier: str | None) -> BitlyProviderAccount:
    statement = select(BitlyProviderAccount).where(
        BitlyProviderAccount.enabled.is_(True),
        BitlyProviderAccount.status == "active",
    )
    if identifier:
        statement = statement.where(identifier_filter(BitlyProviderAccount, identifier))
    account = db.scalar(statement.order_by(BitlyProviderAccount.id).limit(1))
    if account is None:
        raise HTTPException(status_code=409, detail="没有可用的 Bitly 账号")
    return account


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
        raise HTTPException(status_code=500, detail="Bitly Token 无法解密，请重新保存") from None
    return BitlyClient(token, is_mock=account.is_mock)


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
    account = _account_for_create(db, payload.provider_account_id)
    target_url = str(payload.target_url)
    try:
        result = _client(account).create_bitlink(
            target_url=target_url,
            title=payload.title,
            group_guid=account.group_guid,
            domain=account.short_domain,
        )
    except BitlyServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    bitlink_id = str(result.get("id") or "").strip()
    short_url = str(result.get("link") or "").strip()
    if not bitlink_id or not short_url:
        raise HTTPException(status_code=502, detail="Bitly 未返回有效短链")
    link = DirectShortLink(
        public_id=new_public_id("dsl"),
        title=payload.title,
        target_url=target_url,
        bitlink_id=bitlink_id,
        short_url=short_url,
        provider_account_id=account.id,
        enabled=True,
        status="active",
        created_by=current_user.id,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return {"data": {"link": direct_short_link_row(link)}}


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
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from None
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
