from __future__ import annotations

import json
from io import BytesIO
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.exc import IntegrityError

from app.business_schemas import (
    AccountBatchExport,
    AccountGroupCreate,
    AccountGroupUpdate,
    PairRequest,
    PersonalAccountCreate,
    PersonalAccountUpdate,
    SendRequest,
)
from app.deps import CurrentUser, DbSession
from app.entity_ids import identifier_filter
from app.snowflake import new_public_id, parse_snowflake_id

from app.models import (
    AccountMetadataSyncJob,
    AccountPairingAttempt,
    AccountGroup,
    AccountProxyBinding,
    IpAllocationPolicy,
    MessageDelivery,
    PersonalAccount,
    PromotionChannel,
    ProxyEndpoint,
    ProtocolNode,
    RoleActionPermission,
    HyperlinkTask,
)
from app.security import decrypt_secret, utcnow
from app.serializers import iso
from app.services.baileys_credentials import (
    MAX_SESSION_BYTES,
    BaileysCredentialError,
    validate_baileys_session,
)
from app.services.wa_gateway import GatewayError, WaGatewayClient
from app.services.protocol_nodes import (
    marketing_protocol_available,
    normalized_sync_policy,
    select_ingress_protocol,
)
from app.services.account_lifecycle import record_initial_account_state


router = APIRouter(prefix="/api/personal-accounts", tags=["personal-accounts"])
group_router = APIRouter(prefix="/api/account-groups", tags=["account-groups"])

GATEWAY_ACCOUNT_STATES = {
    "unpaired",
    "pairing",
    "linked_offline",
    "warming",
    "online_idle",
    "sending",
    "draining",
    "reauth_required",
    "restricted",
    "disabled",
    "validating",
}


def _group(db: DbSession, group_id: str, user) -> AccountGroup:
    try:
        database_id = parse_snowflake_id(group_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="账号分组不存在") from None
    statement = select(AccountGroup).where(
        AccountGroup.id == database_id,
        AccountGroup.archived_at.is_(None),
    )
    if user.role != "admin":
        statement = statement.where(AccountGroup.created_by == user.id)
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="账号分组不存在")
    return item


def _require_account_export(db: DbSession, user) -> None:
    if user.role == "admin":
        return
    allowed = db.scalar(
        select(RoleActionPermission.id).where(
            RoleActionPermission.role_id == user.group_id,
            RoleActionPermission.permission_key.in_(
                (
                    "resources.accounts.export",
                    "resources.accounts.manage",
                    "business.personal_accounts.manage",
                )
            ),
        )
    )
    if allowed is None:
        raise HTTPException(status_code=403, detail="没有账号导出权限")


def _group_row(db: DbSession, item: AccountGroup) -> dict:
    account_count = int(
        db.scalar(
            select(func.count())
            .select_from(PersonalAccount)
            .where(
                PersonalAccount.group_id == item.id,
                PersonalAccount.archived_at.is_(None),
                PersonalAccount.admission_status == "active",
            )
        )
        or 0
    )
    return {
        "id": str(item.id),
        "name": item.name,
        "description": item.description,
        "createdBy": str(item.created_by),
        "accountCount": account_count,
        "createdAt": iso(item.created_at),
        "updatedAt": iso(item.updated_at),
    }


@group_router.get("")
def list_account_groups(db: DbSession, current_user: CurrentUser) -> dict:
    statement = select(AccountGroup).where(AccountGroup.archived_at.is_(None))
    if current_user.role != "admin":
        statement = statement.where(AccountGroup.created_by == current_user.id)
    items = db.scalars(statement.order_by(AccountGroup.name, AccountGroup.id)).all()
    return {"data": {"rows": [_group_row(db, item) for item in items], "total": len(items)}}


@group_router.post("", status_code=status.HTTP_201_CREATED)
def create_account_group(
    payload: AccountGroupCreate, db: DbSession, current_user: CurrentUser
) -> dict:
    item = AccountGroup(
        public_id=new_public_id("wag"),
        name=payload.name,
        description=payload.description,
        created_by=current_user.id,
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="账号分组名称已存在") from None
    db.refresh(item)
    return {"data": {"group": _group_row(db, item)}}


@group_router.patch("/{group_id}")
def update_account_group(
    group_id: str,
    payload: AccountGroupUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    item = _group(db, group_id, current_user)
    if payload.name is not None:
        item.name = payload.name
    if "description" in payload.model_fields_set:
        item.description = payload.description
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="账号分组名称已存在") from None
    db.refresh(item)
    return {"data": {"group": _group_row(db, item)}}


@group_router.delete("/{group_id}")
def archive_account_group(
    group_id: str, db: DbSession, current_user: CurrentUser
) -> dict:
    item = _group(db, group_id, current_user)
    channel_in_use = db.scalar(
        select(PromotionChannel.id).where(
            PromotionChannel.account_group_id == item.id,
            PromotionChannel.archived_at.is_(None),
        ).limit(1)
    )
    if channel_in_use is not None:
        raise HTTPException(
            status_code=409,
            detail="账号分组仍被推广渠道使用，请先更换渠道的账号入库分组",
        )
    task_in_use = db.scalar(
        select(HyperlinkTask.id).where(
            HyperlinkTask.account_group_id == item.id,
            HyperlinkTask.archived_at.is_(None),
            HyperlinkTask.status.in_(
                ("draft", "queued", "running", "waiting_accounts", "paused")
            ),
        ).limit(1)
    )
    if task_in_use is not None:
        raise HTTPException(
            status_code=409,
            detail="账号分组仍被发送任务使用，请先结束或更换相关任务",
        )
    db.query(PersonalAccount).filter(PersonalAccount.group_id == item.id).update(
        {PersonalAccount.group_id: None}, synchronize_session=False
    )
    item.archived_at = utcnow()
    db.commit()
    return {"data": {"ok": True}}


def _account(db: DbSession, account_id: str, user) -> PersonalAccount:
    try:
        database_id = parse_snowflake_id(account_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="个人账号不存在") from None
    statement = select(PersonalAccount).where(
        PersonalAccount.id == database_id,
        PersonalAccount.archived_at.is_(None),
        PersonalAccount.admission_status == "active",
        )
    if user.role != "admin":
        statement = statement.where(PersonalAccount.created_by == user.id)
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="个人账号不存在")
    return item


def _binding(db: DbSession, account_id: str) -> tuple[AccountProxyBinding, ProxyEndpoint] | None:
    row = db.execute(
        select(AccountProxyBinding, ProxyEndpoint)
        .join(ProxyEndpoint, ProxyEndpoint.id == AccountProxyBinding.proxy_id)
        .where(AccountProxyBinding.account_public_id == account_id)
    ).first()
    return (row[0], row[1]) if row else None


def _proxy_url(db: DbSession, account_id: str) -> str | None:
    row = _binding(db, account_id)
    if row is None:
        return None
    proxy = row[1]
    username = decrypt_secret(proxy.username_ciphertext) if proxy.username_ciphertext else ""
    password = decrypt_secret(proxy.password_ciphertext) if proxy.password_ciphertext else ""
    auth = ""
    if username:
        auth = quote(username, safe="")
        if password:
            auth += ":" + quote(password, safe="")
        auth += "@"
    return f"{proxy.protocol}://{auth}{proxy.host}:{proxy.port}"


def account_row(db: DbSession, item: PersonalAccount) -> dict:
    bound = _binding(db, item.gateway_account_id)
    proxy = bound[1] if bound else None
    group = db.get(AccountGroup, item.group_id) if item.group_id else None
    protocol = db.get(ProtocolNode, item.protocol_id) if item.protocol_id else None
    sent_count = int(db.scalar(select(func.count()).select_from(MessageDelivery).where(MessageDelivery.account_id == item.id, MessageDelivery.status.in_(("sent", "delivered")))) or 0)
    delivered_count = int(db.scalar(select(func.count()).select_from(MessageDelivery).where(MessageDelivery.account_id == item.id, MessageDelivery.status == "delivered")) or 0)
    quality_score = None
    if item.has_avatar is not None and item.group_count is not None:
        quality_score = round(
            (int(item.has_avatar) + int(item.group_count > 0)) / 2 * 100
        )
    return {
        "id": str(item.id),
        "createdBy": str(item.created_by),
        "name": item.name,
        "phone": item.phone_e164,
        "countryCode": item.country_code,
        "status": item.status,
        "source": item.source,
        "sourceRefType": item.source_ref_type,
        "sourceRefId": item.source_ref_id,
        "importFormat": item.import_format,
        "validationStatus": item.validation_status,
        "metadataSyncStatus": item.metadata_sync_status,
        "admissionStatus": item.admission_status,
        "protocol": (
            {
                "id": str(protocol.id),
                "name": protocol.name,
                "type": protocol.protocol_type,
                "online": protocol.online_enabled,
                "ingressEnabled": protocol.ingress_enabled,
                "marketingEnabled": protocol.marketing_enabled,
            }
            if protocol is not None and protocol.archived_at is None
            else None
        ),
        "group": (
            {"id": str(group.id), "name": group.name}
            if group is not None and group.archived_at is None
            else None
        ),
        "quality": {
            "hasAvatar": item.has_avatar,
            "groupCount": item.group_count,
            "friendCount": item.friend_count,
            "mutualContactCount": item.mutual_contact_count,
            "score": quality_score,
            "syncedAt": iso(item.quality_synced_at),
            "isKnown": quality_score is not None,
        },
        "enabled": item.enabled,
        "marketingEligible": item.marketing_eligible,
        "proxyBinding": (
            {
                "bindingId": str(bound[0].id),
                "proxyId": str(proxy.id),
                "proxyName": proxy.name,
                "countryCode": proxy.country_code,
                "healthStatus": proxy.health_status,
            }
            if bound and proxy
            else None
        ),
        "lastError": item.last_error,
        "lastConnectedAt": iso(item.last_connected_at),
        "sentCount": sent_count,
        "deliveredCount": delivered_count,
        "createdAt": iso(item.created_at),
        "updatedAt": iso(item.updated_at),
    }


def delivery_row(item: MessageDelivery) -> dict:
    return {
        "id": str(item.id),
        "messageId": str(item.id),
        "providerMessageId": item.provider_message_id,
        "requestId": item.request_id,
        "to": item.recipient_e164,
        "status": item.status,
        "queuedAt": iso(item.queued_at),
        "sentAt": iso(item.sent_at),
        "deliveredAt": iso(item.delivered_at),
        "failedAt": iso(item.failed_at),
        "lastError": item.last_error,
    }


def _apply_gateway_account(item: PersonalAccount, value: dict) -> None:
    state = str(value.get("state") or "")
    if state in GATEWAY_ACCOUNT_STATES and item.enabled:
        was_online = item.status in {"warming", "online_idle", "sending", "draining"}
        item.status = state
        if state in {"online_idle", "sending"} and not was_online:
            item.last_connected_at = utcnow()
    session_status = value.get("sessionStatus")
    if session_status == "verified" or (
        session_status is None and state in {"online_idle", "sending"}
    ):
        item.validation_status = "ready"
    elif session_status == "pending_verification":
        # Having locally parseable credentials (or merely being offline) is not
        # proof that WhatsApp accepted the imported session.
        item.validation_status = "validating"
    phone = value.get("phoneE164")
    if isinstance(phone, str) and phone:
        item.phone_e164 = phone
    validation_status = value.get("validationStatus")
    if validation_status in {"pending", "validating", "ready", "failed"}:
        item.validation_status = validation_status
    metadata_status = value.get("metadataSyncStatus")
    if metadata_status in {"pending", "syncing", "ready", "failed", "unsupported"}:
        item.metadata_sync_status = metadata_status
    quality = value.get("quality")
    if isinstance(quality, dict):
        quality_known = False
        if isinstance(quality.get("hasAvatar"), bool):
            item.has_avatar = quality["hasAvatar"]
            quality_known = True
        for source_key, attribute in (
            ("groupCount", "group_count"),
            ("friendCount", "friend_count"),
            ("mutualContactCount", "mutual_contact_count"),
        ):
            metric = quality.get(source_key)
            if isinstance(metric, int) and not isinstance(metric, bool) and metric >= 0:
                setattr(item, attribute, metric)
                quality_known = True
        if quality_known:
            item.quality_synced_at = utcnow()
    item.last_error = None


def _sync_gateway_account(
    db: DbSession, item: PersonalAccount, *, strict: bool
) -> None:
    client = WaGatewayClient()
    if client.settings.wa_gateway_mock or not item.phone_e164:
        return
    try:
        _apply_gateway_account(item, client.get(item.gateway_account_id))
    except GatewayError as exc:
        item.last_error = str(exc)
        db.commit()
        if strict:
            raise HTTPException(status_code=502, detail=str(exc)) from None
        return
    db.commit()


def _set_binding(db: DbSession, account_id: str, proxy_id: str | None) -> None:
    existing = db.scalar(
        select(AccountProxyBinding).where(AccountProxyBinding.account_public_id == account_id)
    )
    if not proxy_id:
        if existing:
            db.delete(existing)
        return
    proxy = db.scalar(
        select(ProxyEndpoint).where(
            identifier_filter(ProxyEndpoint, proxy_id),
            ProxyEndpoint.archived_at.is_(None),
            ProxyEndpoint.enabled.is_(True),
        )
    )
    if proxy is None:
        raise HTTPException(status_code=404, detail="可用代理不存在")
    if existing:
        existing.proxy_id = proxy.id
    else:
        db.add(
            AccountProxyBinding(
                public_id=new_public_id("ipb"), account_public_id=account_id, proxy_id=proxy.id
            )
        )


def _group_database_id(
    db: DbSession,
    public_id: str | None,
    user,
    *,
    account_owner_id: int | None = None,
) -> int | None:
    if not public_id:
        return None
    item = _group(db, public_id, user)
    if account_owner_id is not None and item.created_by != account_owner_id:
        raise HTTPException(status_code=409, detail="账号与分组不属于同一客户")
    return item.id


def _auto_proxy(
    db: DbSession, owner_id: int, country_code: str | None
) -> ProxyEndpoint | None:
    policy = db.scalar(
        select(IpAllocationPolicy).where(IpAllocationPolicy.created_by == owner_id)
    )
    mode = policy.allocation_mode if policy else "least_load"
    country_match = policy.country_match if policy else "prefer"
    max_accounts = policy.max_accounts_per_ip if policy else 100
    avoid_unhealthy = policy.avoid_unhealthy if policy else True
    if mode == "manual":
        return None
    statement = (
        select(ProxyEndpoint)
        .outerjoin(
            AccountProxyBinding,
            AccountProxyBinding.proxy_id == ProxyEndpoint.id,
        )
        .where(
            ProxyEndpoint.enabled.is_(True),
            ProxyEndpoint.archived_at.is_(None),
        )
        .group_by(ProxyEndpoint.id)
    )
    if avoid_unhealthy:
        statement = statement.where(ProxyEndpoint.health_status != "unhealthy")
    if mode == "strict_one_to_one":
        statement = statement.having(func.count(AccountProxyBinding.id) == 0)
    else:
        statement = statement.having(
            func.count(AccountProxyBinding.id) < max_accounts
        )
    if mode == "tenant_reuse":
        foreign_binding = (
            select(AccountProxyBinding.id)
            .outerjoin(
                PersonalAccount,
                PersonalAccount.public_id == AccountProxyBinding.account_public_id,
            )
            .where(
                AccountProxyBinding.proxy_id == ProxyEndpoint.id,
                or_(
                    PersonalAccount.id.is_(None),
                    PersonalAccount.created_by != owner_id,
                ),
            )
        )
        statement = statement.where(~exists(foreign_binding))
    health_rank = case((ProxyEndpoint.health_status == "healthy", 0), else_=1)
    if country_code and country_match == "strict":
        statement = statement.where(ProxyEndpoint.country_code == country_code)
        statement = statement.order_by(
            health_rank, func.count(AccountProxyBinding.id), ProxyEndpoint.id
        )
    elif country_code and country_match == "prefer":
        statement = statement.order_by(
            health_rank,
            case((ProxyEndpoint.country_code == country_code, 0), else_=1),
            func.count(AccountProxyBinding.id),
            ProxyEndpoint.id,
        )
    else:
        statement = statement.order_by(
            health_rank, func.count(AccountProxyBinding.id), ProxyEndpoint.id
        )
    return db.scalar(statement.limit(1))


@router.get("")
def list_accounts(
    db: DbSession,
    current_user: CurrentUser,
    keyword: str | None = None,
    account_status: str | None = Query(default=None, alias="status"),
    sync: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
) -> dict:
    statement = select(PersonalAccount).where(
        PersonalAccount.archived_at.is_(None),
        PersonalAccount.admission_status == "active",
    )
    if current_user.role != "admin":
        statement = statement.where(PersonalAccount.created_by == current_user.id)
    if keyword:
        pattern = f"%{keyword.strip()}%"
        statement = statement.where(
            or_(PersonalAccount.name.ilike(pattern), PersonalAccount.phone_e164.ilike(pattern))
        )
    if account_status and account_status != "all":
        statement = statement.where(PersonalAccount.status == account_status)
    total = int(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    items = db.scalars(
        statement.order_by(PersonalAccount.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    if sync and items:
        try:
            gateway_accounts = {
                str(value.get("id")): value for value in WaGatewayClient().list()
            }
            for item in items:
                if item.gateway_account_id in gateway_accounts:
                    _apply_gateway_account(
                        item, gateway_accounts[item.gateway_account_id]
                    )
            db.commit()
        except GatewayError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from None
    return {"data": {"rows": [account_row(db, item) for item in items], "total": total, "page": page, "pageSize": page_size}}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_account(payload: PersonalAccountCreate, db: DbSession, current_user: CurrentUser) -> dict:
    if payload.proxy_id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="固定代理由管理员分配")
    proxy_id = payload.proxy_id
    if not proxy_id:
        proxy = _auto_proxy(db, current_user.id, payload.country_code)
        if proxy is not None:
            proxy_id = str(proxy.id)
        elif not WaGatewayClient().settings.wa_gateway_mock:
            raise HTTPException(
                status_code=409,
                detail="没有可用固定代理，已阻止账号裸连；手动模式下请先选择 IP",
            )
    protocol = select_ingress_protocol(
        db, current_user.id, payload.protocol_id
    )
    item = PersonalAccount(
        public_id=new_public_id("wa"),
        name=payload.name,
        phone_e164=payload.phone,
        country_code=payload.country_code,
        status="unpaired" if payload.enabled else "disabled",
        source="landing_page",
        source_ref_type=payload.source_ref_type,
        source_ref_id=payload.source_ref_id,
        validation_status="pending",
        metadata_sync_status="pending",
        admission_status="active",
        group_id=_group_database_id(
            db,
            payload.group_id,
            current_user,
            account_owner_id=current_user.id,
        ),
        protocol_id=protocol.id,
        enabled=payload.enabled,
        marketing_eligible=payload.marketing_eligible,
        created_by=current_user.id,
    )
    db.add(item)
    client = WaGatewayClient()
    gateway_attempted = False
    try:
        db.flush()
        _set_binding(db, item.gateway_account_id, proxy_id)
        db.flush()
        if item.phone_e164:
            gateway_attempted = True
            client.create(
                item.gateway_account_id,
                item.phone_e164,
                _proxy_url(db, item.gateway_account_id),
                connection_policy=protocol.connection_policy,
                idle_disconnect_seconds=protocol.idle_disconnect_seconds,
                post_verify_grace_seconds=protocol.post_verify_grace_seconds,
                sync_policy=normalized_sync_policy(protocol.sync_policy_json),
            )
        record_initial_account_state(
            db, item, reason_category="account_created"
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        if gateway_attempted:
            try:
                client.logout(item.gateway_account_id)
            except GatewayError:
                pass
        raise HTTPException(status_code=409, detail="手机号已被其他个人账号使用") from None
    except GatewayError as exc:
        db.rollback()
        # A timeout may happen after the Baileys gateway persisted the account.
        # Best-effort cleanup keeps a subsequent user retry from hitting 409.
        if gateway_attempted:
            try:
                client.logout(item.gateway_account_id)
            except GatewayError:
                pass
        raise HTTPException(status_code=502, detail=str(exc)) from None
    db.refresh(item)
    return {"data": {"account": account_row(db, item)}}


@router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_account(
    db: DbSession,
    current_user: CurrentUser,
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    group_id: str | None = Form(default=None, alias="groupId"),
    proxy_id: str | None = Form(default=None, alias="proxyId"),
    legacy_proxy_public_id: str | None = Form(default=None, alias="proxyPublicId"),
    protocol_id: str | None = Form(default=None, alias="protocolId"),
) -> dict:
    requested_proxy_id = proxy_id or legacy_proxy_public_id
    if requested_proxy_id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="固定代理由管理员分配")
    if not (file.filename or "").lower().endswith(".json"):
        raise HTTPException(status_code=422, detail="只允许导入 JSON 文件")
    raw = await file.read(MAX_SESSION_BYTES + 1)
    if len(raw) > MAX_SESSION_BYTES:
        raise HTTPException(status_code=413, detail="导入文件不能超过 10MB")
    try:
        document = json.loads(
            raw.decode("utf-8"),
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON number")
            ),
        )
    except (RecursionError, UnicodeDecodeError, ValueError):
        raise HTTPException(status_code=422, detail="导入文件不是有效 UTF-8 JSON") from None
    try:
        session = validate_baileys_session(document)
    except BaileysCredentialError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    normalized_name = (name or session.display_name or session.phone_e164).strip()
    if not normalized_name or len(normalized_name) > 120:
        raise HTTPException(status_code=422, detail="账号名称长度必须为 1-120 个字符")
    selected_proxy_id = requested_proxy_id
    if not selected_proxy_id:
        proxy = _auto_proxy(db, current_user.id, None)
        if proxy is not None:
            selected_proxy_id = str(proxy.id)
        elif not WaGatewayClient().settings.wa_gateway_mock:
            raise HTTPException(
                status_code=409,
                detail="没有可用固定代理，已阻止账号裸连；手动模式下请在导入时选择 IP",
            )

    protocol = select_ingress_protocol(db, current_user.id, protocol_id)
    item = PersonalAccount(
        public_id=new_public_id("wa"),
        name=normalized_name,
        phone_e164=session.phone_e164,
        status="validating",
        source="json_import",
        import_format=session.import_format,
        validation_status="validating",
        metadata_sync_status="pending",
        admission_status="active",
        group_id=_group_database_id(
            db,
            group_id,
            current_user,
            account_owner_id=current_user.id,
        ),
        protocol_id=protocol.id,
        enabled=True,
        created_by=current_user.id,
    )
    db.add(item)
    client = WaGatewayClient()
    gateway_attempted = False
    try:
        db.flush()
        _set_binding(db, item.gateway_account_id, selected_proxy_id)
        db.flush()
        gateway_attempted = True
        client.import_session(
            item.gateway_account_id,
            session.value,
            _proxy_url(db, item.gateway_account_id),
        )
        # Import acceptance is not proof that the remote session is usable.
        # A later gateway sync promotes validation_status to ready.
        record_initial_account_state(
            db, item, reason_category="session_imported"
        )
        from app.services.account_metadata_sync import enqueue_account_metadata_sync

        enqueue_account_metadata_sync(
            db,
            item,
            sync_policy=normalized_sync_policy(protocol.sync_policy_json),
            sync_policy_version=protocol.sync_policy_version,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        if gateway_attempted:
            try:
                client.disconnect(item.gateway_account_id)
            except GatewayError:
                pass
        raise HTTPException(status_code=409, detail="该手机号已存在于账号池") from None
    except GatewayError as exc:
        db.rollback()
        if gateway_attempted:
            try:
                client.disconnect(item.gateway_account_id)
            except GatewayError:
                pass
        raise HTTPException(status_code=502, detail=str(exc)) from None
    db.refresh(item)
    return {"data": {"account": account_row(db, item)}}


def _unknown_aware_metric(values: list[object], predicate) -> dict:
    known = [value for value in values if value is not None]
    count = sum(1 for value in known if predicate(value))
    return {
        "count": count,
        "knownCount": len(known),
        "unknownCount": len(values) - len(known),
        "rate": round(count / len(known) * 100, 2) if known else None,
    }


@router.get("/statistics")
def account_statistics(db: DbSession, current_user: CurrentUser) -> dict:
    statement = select(PersonalAccount).where(
        PersonalAccount.archived_at.is_(None),
        PersonalAccount.admission_status == "active",
    )
    if current_user.role != "admin":
        statement = statement.where(PersonalAccount.created_by == current_user.id)
    items = list(db.scalars(statement).all())
    validation = {
        key: sum(1 for item in items if item.validation_status == key)
        for key in ("pending", "validating", "ready", "failed")
    }
    scores = [
        (int(item.has_avatar) + int(item.group_count > 0)) / 2 * 100
        for item in items
        if item.has_avatar is not None and item.group_count is not None
    ]
    quality = {
        "noAvatar": _unknown_aware_metric(
            [item.has_avatar for item in items], lambda value: value is False
        ),
        "noGroup": _unknown_aware_metric(
            [item.group_count for item in items], lambda value: value == 0
        ),
        "zeroFriends": _unknown_aware_metric(
            [item.friend_count for item in items], lambda value: value == 0
        ),
        "zeroMutualContacts": _unknown_aware_metric(
            [item.mutual_contact_count for item in items], lambda value: value == 0
        ),
        "score": {
            "average": round(sum(scores) / len(scores), 2) if scores else None,
            "knownCount": len(scores),
            "unknownCount": len(items) - len(scores),
        },
    }
    rows = []
    for item in items:
        score = None
        if item.has_avatar is not None and item.group_count is not None:
            score = round(
                (int(item.has_avatar) + int(item.group_count > 0)) / 2 * 100
            )
        rows.append(
            {
                "accountId": str(item.id),
                "displayName": item.name,
                "phone": item.phone_e164,
                "source": item.source,
                "hasAvatar": item.has_avatar,
                "groupCount": item.group_count,
                "friendCount": item.friend_count,
                "mutualCount": item.mutual_contact_count,
                "score": score,
                "syncStatus": (
                    "synced" if item.metadata_sync_status == "ready"
                    else item.metadata_sync_status
                ),
            }
        )
    summary = {
        "totalAccounts": len(items),
        "onlineAccounts": sum(
            1 for item in items if item.status in {"online_idle", "sending"}
        ),
        "importedAccounts": sum(1 for item in items if item.source == "json_import"),
        "pendingSyncAccounts": sum(
            1 for item in items if item.metadata_sync_status != "ready"
        ),
    }
    return {
        "data": {
            "total": len(items),
            "summary": summary,
            "rows": rows,
            "validation": validation,
            "quality": quality,
        }
    }


@router.get("/{account_id}")
def get_account(account_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    item = _account(db, account_id, current_user)
    _sync_gateway_account(db, item, strict=False)
    return {"data": {"account": account_row(db, item)}}


@router.get("/{account_id}/export")
def export_account(
    account_id: str,
    db: DbSession,
    current_user: CurrentUser,
    export_format: str = Query(default="baileys_creds", alias="format"),
) -> Response:
    _require_account_export(db, current_user)
    if export_format not in {"baileys_creds", "native"}:
        raise HTTPException(status_code=422, detail="不支持的账号导出格式")
    item = _account(db, account_id, current_user)
    if item.validation_status != "ready":
        raise HTTPException(status_code=409, detail="账号验证完成后才能导出")
    if item.status in {"pairing", "warming", "online_idle", "sending", "draining"}:
        raise HTTPException(status_code=409, detail="请先断开账号连接再导出凭据")
    try:
        exported_session = WaGatewayClient().export_session(
            item.gateway_account_id
        )
    except GatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    if not isinstance(exported_session, dict):
        raise HTTPException(status_code=502, detail="网关未返回有效的 Baileys 会话")
    try:
        validated_session = validate_baileys_session(exported_session)
    except BaileysCredentialError:
        raise HTTPException(
            status_code=502, detail="网关返回的 Baileys 会话不完整，已阻止导出"
        ) from None
    document = (
        validated_session.value
        if export_format == "native"
        else validated_session.credentials.value
    )
    suffix = "-parloq-full" if export_format == "native" else ""
    filename = f"{(item.phone_e164 or str(item.id)).lstrip('+')}{suffix}.json"
    return Response(
        content=json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store, private",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "X-Parloq-Export-Format": export_format,
        },
    )


@router.post("/export/batch")
def export_accounts_batch(
    payload: AccountBatchExport,
    db: DbSession,
    current_user: CurrentUser,
) -> Response:
    _require_account_export(db, current_user)
    database_ids = [parse_snowflake_id(value) for value in payload.account_ids]
    statement = select(PersonalAccount).where(
        PersonalAccount.id.in_(database_ids),
        PersonalAccount.archived_at.is_(None),
        PersonalAccount.admission_status == "active",
    )
    if current_user.role != "admin":
        statement = statement.where(PersonalAccount.created_by == current_user.id)
    items = {str(item.id): item for item in db.scalars(statement).all()}
    missing = [account_id for account_id in payload.account_ids if account_id not in items]
    if missing:
        raise HTTPException(status_code=404, detail="部分账号不存在或无权导出")

    for account_id in payload.account_ids:
        item = items[account_id]
        if item.validation_status != "ready":
            raise HTTPException(
                status_code=409,
                detail=f"账号 {item.phone_e164 or item.id} 尚未验证完成",
            )
        if item.status in {"pairing", "warming", "online_idle", "sending", "draining"}:
            raise HTTPException(
                status_code=409,
                detail=f"账号 {item.phone_e164 or item.id} 在线，请先断开后导出",
            )

    archive = BytesIO()
    gateway = WaGatewayClient()
    with ZipFile(archive, mode="w", compression=ZIP_DEFLATED) as bundle:
        for account_id in payload.account_ids:
            item = items[account_id]
            try:
                exported_session = gateway.export_session(
                    item.gateway_account_id
                )
            except GatewayError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from None
            if not isinstance(exported_session, dict):
                raise HTTPException(status_code=502, detail="网关未返回有效的 Baileys 会话")
            try:
                validated_session = validate_baileys_session(exported_session)
            except BaileysCredentialError:
                raise HTTPException(
                    status_code=502,
                    detail=f"账号 {item.phone_e164 or item.id} 的会话不完整",
                ) from None
            document = (
                validated_session.value
                if payload.export_format == "native"
                else validated_session.credentials.value
            )
            suffix = "-parloq-full" if payload.export_format == "native" else ""
            filename = f"{(item.phone_e164 or str(item.id)).lstrip('+')}{suffix}.json"
            bundle.writestr(
                filename,
                json.dumps(
                    document,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
            )
    archive.seek(0)
    return Response(
        content=archive.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="parloq-accounts.zip"',
            "Cache-Control": "no-store, private",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/sync-all")
def sync_all_accounts(db: DbSession, current_user: CurrentUser) -> dict:
    statement = select(PersonalAccount).where(
        PersonalAccount.archived_at.is_(None),
        PersonalAccount.admission_status == "active",
    )
    if current_user.role != "admin":
        statement = statement.where(PersonalAccount.created_by == current_user.id)
    items = db.scalars(statement).all()
    from app.services.account_metadata_sync import enqueue_account_metadata_sync

    queued = 0
    for item in items:
        enqueue_account_metadata_sync(db, item)
        queued += 1
    db.commit()
    return {"data": {"queuedCount": queued, "total": len(items)}}


@router.get("/intake/attempts")
def list_intake_attempts(
    db: DbSession,
    current_user: CurrentUser,
    keyword: str | None = None,
    attempt_status: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
) -> dict:
    statement = (
        select(AccountPairingAttempt, PersonalAccount)
        .join(PersonalAccount, PersonalAccount.id == AccountPairingAttempt.account_id)
        .where(PersonalAccount.archived_at.is_(None))
    )
    if current_user.role != "admin":
        statement = statement.where(PersonalAccount.created_by == current_user.id)
    if attempt_status and attempt_status != "all":
        statement = statement.where(AccountPairingAttempt.status == attempt_status)
    if keyword:
        pattern = f"%{keyword.strip()}%"
        statement = statement.where(
            or_(
                PersonalAccount.name.ilike(pattern),
                PersonalAccount.phone_e164.ilike(pattern),
                AccountPairingAttempt.public_id.ilike(pattern),
            )
        )
    total = int(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = db.execute(
        statement.order_by(AccountPairingAttempt.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    result = []
    for attempt, account in rows:
        channel = db.get(PromotionChannel, attempt.channel_id)
        protocol = db.get(ProtocolNode, attempt.protocol_node_id)
        group = db.get(AccountGroup, attempt.account_group_id)
        latest_job = db.scalar(
            select(AccountMetadataSyncJob)
            .where(AccountMetadataSyncJob.account_id == account.id)
            .order_by(AccountMetadataSyncJob.created_at.desc())
            .limit(1)
        )
        result.append(
            {
                "id": str(attempt.id),
                "attemptType": attempt.attempt_type,
                "status": attempt.status,
                "terminalReason": attempt.terminal_reason,
                "providerCode": attempt.provider_code,
                "visitorId": attempt.visitor_id,
                "account": {
                    "id": str(account.id),
                    "name": account.name,
                    "phone": account.phone_e164,
                    "admissionStatus": account.admission_status,
                    "status": account.status,
                    "validationStatus": account.validation_status,
                    "metadataSyncStatus": account.metadata_sync_status,
                },
                "channel": (
                    {"id": str(channel.id), "name": channel.name}
                    if channel is not None
                    else None
                ),
                "protocol": (
                    {"id": str(protocol.id), "name": protocol.name}
                    if protocol is not None
                    else None
                ),
                "group": (
                    {"id": str(group.id), "name": group.name}
                    if group is not None
                    else None
                ),
                "routeVersion": attempt.route_version,
                "syncPolicyVersion": attempt.sync_policy_version,
                "syncJob": (
                    {
                        "id": str(latest_job.id),
                        "status": latest_job.status,
                        "lastError": latest_job.last_error,
                    }
                    if latest_job is not None
                    else None
                ),
                "expiresAt": iso(attempt.expires_at),
                "verifiedAt": iso(attempt.verified_at),
                "createdAt": iso(attempt.created_at),
                "updatedAt": iso(attempt.updated_at),
            }
        )
    return {
        "data": {
            "rows": result,
            "total": total,
            "page": page,
            "pageSize": page_size,
        }
    }


@router.patch("/{account_id}")
def update_account(account_id: str, payload: PersonalAccountUpdate, db: DbSession, current_user: CurrentUser) -> dict:
    item = _account(db, account_id, current_user)
    if "proxy_id" in payload.model_fields_set and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="固定代理由管理员分配")
    gateway_changes: dict = {}
    previous_group_id = item.group_id
    if payload.name is not None:
        item.name = payload.name
    if "phone" in payload.model_fields_set:
        item.phone_e164 = payload.phone
        if payload.phone:
            gateway_changes["phone_e164"] = payload.phone
    if "country_code" in payload.model_fields_set:
        item.country_code = payload.country_code
    if "group_id" in payload.model_fields_set:
        item.group_id = _group_database_id(
            db,
            payload.group_id,
            current_user,
            account_owner_id=item.created_by,
        )
    if payload.enabled is not None:
        item.enabled = payload.enabled
        if not payload.enabled:
            item.status = "disabled"
        elif item.status == "disabled":
            item.status = "unpaired"
    if payload.marketing_eligible is not None:
        item.marketing_eligible = payload.marketing_eligible
    if "proxy_id" in payload.model_fields_set:
        _set_binding(db, item.gateway_account_id, payload.proxy_id)
    wakeup_group_id = (
        item.group_id
        if item.group_id is not None
        and (
            item.group_id != previous_group_id
            or payload.enabled is True
        )
        else None
    )
    if wakeup_group_id is not None:
        from app.services.account_group_wakeups import record_group_wakeup

        record_group_wakeup(
            db,
            wakeup_group_id,
            reason=(
                "account_joined_group"
                if item.group_id != previous_group_id
                else "account_enabled"
            ),
            account_id=item.id,
        )
    try:
        db.flush()
        if "proxy_id" in payload.model_fields_set:
            gateway_changes["proxy_url"] = _proxy_url(
                db, item.gateway_account_id
            )
        if gateway_changes and item.phone_e164:
            WaGatewayClient().update(
                item.gateway_account_id, **gateway_changes
            )
        db.commit()
    except GatewayError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="手机号已被其他个人账号使用") from None
    db.refresh(item)
    if wakeup_group_id is not None:
        from app.services.account_group_wakeups import (
            dispatch_group_wakeups_best_effort,
        )

        dispatch_group_wakeups_best_effort(wakeup_group_id)
    return {"data": {"account": account_row(db, item)}}


@router.delete("/{account_id}")
def archive_account(account_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    item = _account(db, account_id, current_user)
    try:
        WaGatewayClient().logout(item.gateway_account_id)
    except GatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    binding = db.scalar(select(AccountProxyBinding).where(AccountProxyBinding.account_public_id == item.gateway_account_id))
    if binding:
        db.delete(binding)
    item.enabled = False
    item.status = "disabled"
    item.archived_at = utcnow()
    db.commit()
    return {"data": {"ok": True}}


@router.post("/{account_id}/pairing-code")
def pairing_code(account_id: str, payload: PairRequest, db: DbSession, current_user: CurrentUser) -> dict:
    item = _account(db, account_id, current_user)
    phone = payload.phone or item.phone_e164
    if payload.method == "pairing_code" and not phone:
        raise HTTPException(status_code=422, detail="配对码方式必须提供手机号")
    try:
        client = WaGatewayClient()
        protocol = db.get(ProtocolNode, item.protocol_id)
        if protocol is None:
            raise HTTPException(status_code=409, detail="账号所属协议节点不存在")
        if not item.phone_e164 and phone:
            client.create(
                item.gateway_account_id,
                phone,
                _proxy_url(db, item.gateway_account_id),
                connection_policy=protocol.connection_policy,
                idle_disconnect_seconds=protocol.idle_disconnect_seconds,
                post_verify_grace_seconds=protocol.post_verify_grace_seconds,
                sync_policy=normalized_sync_policy(protocol.sync_policy_json),
            )
        else:
            client.update(
                item.gateway_account_id,
                connection_policy=protocol.connection_policy,
                idle_disconnect_seconds=protocol.idle_disconnect_seconds,
                post_verify_grace_seconds=protocol.post_verify_grace_seconds,
                sync_policy=normalized_sync_policy(protocol.sync_policy_json),
            )
        result = client.pair(
            item.gateway_account_id,
            phone,
            payload.method,
            _proxy_url(db, item.gateway_account_id),
        )
    except GatewayError as exc:
        item.last_error = str(exc)
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from None
    item.phone_e164 = phone
    item.status = "linked_offline" if WaGatewayClient().settings.wa_gateway_mock else "pairing"
    item.last_error = None
    db.commit()
    return {"data": {"pairingCode": result.get("code"), "qrPayload": result.get("qrPayload"), "expiresAt": result.get("expiresAt"), "account": account_row(db, item)}}


@router.post("/{account_id}/connect")
def connect(account_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    item = _account(db, account_id, current_user)
    if item.status in {"unpaired", "disabled"}:
        raise HTTPException(status_code=409, detail="账号尚未配对或已停用")
    try:
        client = WaGatewayClient()
        result = (
            client.connect(item.gateway_account_id)
            if item.status in {"warming", "online_idle", "sending", "draining"}
            else client.connect(
                item.gateway_account_id,
                _proxy_url(db, item.gateway_account_id),
            )
        )
    except GatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    _apply_gateway_account(item, result or {"state": "online_idle"})
    item.last_connected_at = item.last_connected_at or utcnow()
    db.commit()
    return {"data": {"account": account_row(db, item)}}


@router.post("/{account_id}/disconnect")
def disconnect(account_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    item = _account(db, account_id, current_user)
    try:
        result = WaGatewayClient().disconnect(item.gateway_account_id)
    except GatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    _apply_gateway_account(item, result or {"state": "linked_offline"})
    db.commit()
    return {"data": {"account": account_row(db, item)}}


@router.post("/{account_id}/logout")
def logout(account_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    item = _account(db, account_id, current_user)
    try:
        result = WaGatewayClient().logout(item.gateway_account_id)
    except GatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    _apply_gateway_account(item, result or {"state": "unpaired"})
    item.last_connected_at = None
    db.commit()
    return {"data": {"account": account_row(db, item)}}


def send_message(db: DbSession, item: PersonalAccount, payload: SendRequest) -> MessageDelivery:
    if not item.marketing_eligible:
        raise HTTPException(status_code=409, detail="账号未开启营销参与")
    if not marketing_protocol_available(db, item.protocol_id):
        raise HTTPException(status_code=409, detail="账号所属协议未开启营销")
    existing = db.scalar(select(MessageDelivery).where(MessageDelivery.request_id == payload.idempotency_key))
    if existing:
        return existing
    delivery = MessageDelivery(
        public_id=new_public_id("msg"), request_id=payload.idempotency_key,
        account_id=item.id, recipient_e164=payload.to, status="queued", queued_at=utcnow(),
    )
    db.add(delivery)
    db.commit()
    try:
        result = WaGatewayClient().send(
            item.gateway_account_id,
            delivery.public_id,
            payload.to,
            payload.message,
        )
        delivery.provider_message_id = str(result.get("providerMessageId") or "") or None
        # HTTP 202 only means the gateway durably accepted the queue item.  One
        # tick and two ticks are advanced exclusively by signed status events.
        delivery.status = "queued"
    except GatewayError as exc:
        delivery.status = "failed"
        delivery.failed_at = utcnow()
        delivery.last_error = str(exc)
    db.commit()
    db.refresh(delivery)
    return delivery


@router.post("/{account_id}/send")
def send(account_id: str, payload: SendRequest, db: DbSession, current_user: CurrentUser) -> dict:
    item = _account(db, account_id, current_user)
    if item.status != "online_idle":
        raise HTTPException(status_code=409, detail="账号未在线")
    return {"data": {"messageDelivery": delivery_row(send_message(db, item, payload))}}


@router.post("/{account_id}/sync", status_code=status.HTTP_202_ACCEPTED)
def sync_account(account_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    item = _account(db, account_id, current_user)
    from app.services.account_metadata_sync import (
        enqueue_account_metadata_sync,
        metadata_sync_job_row,
    )

    job = enqueue_account_metadata_sync(db, item)
    db.commit()
    db.refresh(job)
    return {
        "data": {
            "account": account_row(db, item),
            "syncJob": metadata_sync_job_row(job),
        }
    }


@router.get("/{account_id}/messages")
def list_messages(account_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    item = _account(db, account_id, current_user)
    rows = db.scalars(select(MessageDelivery).where(MessageDelivery.account_id == item.id).order_by(MessageDelivery.created_at.desc()).limit(500)).all()
    return {"data": {"rows": [delivery_row(row) for row in rows], "total": len(rows)}}
