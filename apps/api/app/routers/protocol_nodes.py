from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.business_schemas import (
    ProtocolBatchAction,
    ProtocolNodeCreate,
    ProtocolNodeUpdate,
    ProtocolPoolCreate,
    ProtocolPoolUpdate,
)
from app.deps import CurrentUser, DbSession
from app.entity_ids import entity_id, identifier_filter, identifiers_filter, matches_identifier
from app.models import (
    AccountMetadataSyncJob,
    AccountPairingAttempt,
    PersonalAccount,
    PromotionChannel,
    ProtocolDefinition,
    ProtocolNode,
    ProtocolPool,
    ProtocolPoolMember,
)
from app.snowflake import new_public_id
from app.services.protocol_nodes import (
    DEFAULT_SYNC_POLICY,
    default_protocol_definition,
    ingress_unavailable_reason,
    normalized_rate_limit_policy,
    normalized_sync_policy,
    protocol_capacity,
    select_ingress_protocol,
)
from app.services.account_group_wakeups import (
    dispatch_group_wakeups_best_effort,
    record_group_wakeup,
)
from app.services.wa_gateway import GatewayError, WaGatewayClient


router = APIRouter(prefix="/api/protocol-nodes", tags=["protocol-nodes"])
pool_router = APIRouter(prefix="/api/protocol-pools", tags=["protocol-pools"])

_ONLINE_STATES = {"warming", "online_idle", "sending", "draining"}


def _account_proxy_url(db: DbSession, account_id: str) -> str | None:
    # Import lazily so the two API routers do not depend on import order.
    from app.routers.personal_accounts import _proxy_url

    return _proxy_url(db, account_id)
_INVALID_STATES = {
    "unpaired",
    "pairing",
    "validating",
    "reauth_required",
    "restricted",
    "disabled",
}


def _safe_gateway_error(exc: GatewayError) -> str:
    message = str(exc)[:500]
    return re.sub(
        r"((?:https?|socks5h?|socks)://)[^@\s/]+@",
        r"\1[REDACTED]@",
        message,
        flags=re.IGNORECASE,
    )


def _scope(statement, user):
    return (
        statement
        if user.role == "admin"
        else statement.where(ProtocolNode.created_by == user.id)
    )


def _node(db: DbSession, identifier: str, user) -> ProtocolNode:
    item = db.scalar(
        _scope(
            select(ProtocolNode).where(
                identifier_filter(ProtocolNode, identifier),
            ),
            user,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="节点不存在")
    return item


def _definition_payload(item: ProtocolDefinition) -> dict:
    return {
        "id": entity_id(item),
        "name": item.name,
        "adapterKey": item.adapter_key,
        "version": item.version,
        "buildStatus": item.build_status,
        "enabled": item.enabled,
    }


def _row(
    db: DbSession,
    item: ProtocolNode,
    *,
    definition: ProtocolDefinition | None = None,
) -> dict:
    definition = definition or db.get(
        ProtocolDefinition,
        item.protocol_definition_id,
    )
    if definition is None:
        raise HTTPException(status_code=500, detail="节点绑定的协议不存在")
    account_states = list(
        db.execute(
            select(PersonalAccount.status, PersonalAccount.validation_status).where(
                PersonalAccount.protocol_id == item.id,
                PersonalAccount.admission_status == "active",
            )
        ).all()
    )
    total = len(account_states)
    valid = sum(
        validation == "ready" and status not in _INVALID_STATES
        for status, validation in account_states
    )
    online = sum(
        validation == "ready" and status in _ONLINE_STATES
        for status, validation in account_states
    )
    capacity = protocol_capacity(db, item)
    unavailable_reason = ingress_unavailable_reason(item, capacity)
    health_status = (
        "available"
        if unavailable_reason is None
        else "capacity_limited"
        if "上限" in unavailable_reason
        else "offline"
    )
    return {
        "id": entity_id(item),
        "name": item.name,
        "protocol": item.protocol_type,
        "protocolDefinition": _definition_payload(definition),
        "remark": item.remark,
        "ingressEnabled": item.ingress_enabled,
        "marketingEnabled": item.marketing_enabled,
        "online": item.online_enabled,
        "healthStatus": health_status,
        "healthReason": unavailable_reason,
        "accountTotal": total,
        "validAccounts": valid,
        "onlineAccounts": online,
        "validRate": round(valid / total * 100, 2) if total else None,
        "onlineRate": round(online / valid * 100, 2) if valid else None,
        "activePairingCount": capacity.active_pairings,
        "maxAccountCount": item.max_account_count,
        "maxOnlineAccounts": item.max_online_accounts,
        "maxConcurrentPairings": item.max_concurrent_pairings,
        "connectionPolicy": item.connection_policy,
        "idleDisconnectSeconds": item.idle_disconnect_seconds,
        "postVerifyGraceSeconds": item.post_verify_grace_seconds,
        "syncPolicyVersion": item.sync_policy_version,
        "syncPolicy": normalized_sync_policy(item.sync_policy_json),
        "rateLimitPolicy": normalized_rate_limit_policy(
            item.rate_limit_policy_json
        ),
        "createdAt": item.created_at.isoformat(),
        "updatedAt": item.updated_at.isoformat(),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_protocol_node(
    payload: ProtocolNodeCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    if payload.protocol_definition_id is None:
        definition = default_protocol_definition(db)
    else:
        definition = db.scalar(
            select(ProtocolDefinition).where(
                identifier_filter(
                    ProtocolDefinition,
                    payload.protocol_definition_id,
                )
            )
        )
    if definition is None:
        raise HTTPException(status_code=404, detail="协议不存在")
    if definition.build_status != "ready" or not definition.enabled:
        raise HTTPException(status_code=409, detail="该协议尚未构建完成，不能创建节点")
    item = ProtocolNode(
        public_id=new_public_id("proto"),
        name=payload.name,
        protocol_type=definition.adapter_key,
        protocol_definition_id=definition.id,
        remark=payload.remark,
        ingress_enabled=payload.ingress_enabled,
        marketing_enabled=payload.marketing_enabled,
        online_enabled=True,
        max_account_count=payload.max_account_count,
        max_online_accounts=payload.max_online_accounts,
        max_concurrent_pairings=payload.max_concurrent_pairings,
        connection_policy=payload.connection_policy,
        idle_disconnect_seconds=payload.idle_disconnect_seconds,
        post_verify_grace_seconds=payload.post_verify_grace_seconds,
        sync_policy_version=1,
        sync_policy_json=payload.sync_policy.model_dump(by_alias=True),
        rate_limit_policy_json=payload.rate_limit_policy.model_dump(by_alias=True),
        created_by=current_user.id,
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="节点名称已存在") from None
    db.refresh(item)
    return {"data": {"protocol": _row(db, item, definition=definition)}}


@router.get("")
def list_protocol_nodes(db: DbSession, current_user: CurrentUser) -> dict:
    owner_has_node = db.scalar(
        select(ProtocolNode.id).where(
            ProtocolNode.created_by == current_user.id,
        ).limit(1)
    )
    if current_user.role != "admin" and owner_has_node is None:
        select_ingress_protocol(db, current_user.id)
        db.commit()
    statement = _scope(select(ProtocolNode), current_user)
    items = db.scalars(statement.order_by(ProtocolNode.id)).all()
    definition_ids = {item.protocol_definition_id for item in items}
    definitions = {
        item.id: item
        for item in db.scalars(
            select(ProtocolDefinition).where(
                ProtocolDefinition.id.in_(definition_ids)
            )
        ).all()
    } if definition_ids else {}
    return {
        "data": {
            "rows": [
                _row(
                    db,
                    item,
                    definition=definitions.get(item.protocol_definition_id),
                )
                for item in items
            ],
            "total": len(items),
        }
    }


@router.patch("/{protocol_id}")
def update_protocol_node(
    protocol_id: str,
    payload: ProtocolNodeUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    item = _node(db, protocol_id, current_user)
    marketing_was_enabled = item.marketing_enabled
    selected_definition: ProtocolDefinition | None = None
    if "protocol_definition_id" in payload.model_fields_set:
        if payload.protocol_definition_id is None:
            raise HTTPException(status_code=422, detail="节点必须绑定协议")
        selected_definition = db.scalar(
            select(ProtocolDefinition).where(
                identifier_filter(
                    ProtocolDefinition,
                    payload.protocol_definition_id,
                )
            )
        )
        if selected_definition is None:
            raise HTTPException(status_code=404, detail="协议不存在")
        if selected_definition.build_status != "ready" or not selected_definition.enabled:
            raise HTTPException(status_code=409, detail="该协议尚未构建完成")
        if (
            selected_definition.id != item.protocol_definition_id
            and db.scalar(
                select(PersonalAccount.id).where(
                    PersonalAccount.protocol_id == item.id
                ).limit(1)
            ) is not None
        ):
            raise HTTPException(status_code=409, detail="已有账号的节点不能直接切换协议")
        item.protocol_definition_id = selected_definition.id
        item.protocol_type = selected_definition.adapter_key
    if payload.name is not None:
        item.name = payload.name
    if "remark" in payload.model_fields_set:
        item.remark = payload.remark
    if payload.ingress_enabled is not None:
        item.ingress_enabled = payload.ingress_enabled
    if payload.marketing_enabled is not None:
        item.marketing_enabled = payload.marketing_enabled
    if "max_account_count" in payload.model_fields_set:
        item.max_account_count = payload.max_account_count
    if "max_online_accounts" in payload.model_fields_set:
        item.max_online_accounts = payload.max_online_accounts
    if "max_concurrent_pairings" in payload.model_fields_set:
        item.max_concurrent_pairings = payload.max_concurrent_pairings
    if payload.connection_policy is not None:
        item.connection_policy = payload.connection_policy
    if payload.idle_disconnect_seconds is not None:
        item.idle_disconnect_seconds = payload.idle_disconnect_seconds
    if payload.post_verify_grace_seconds is not None:
        item.post_verify_grace_seconds = payload.post_verify_grace_seconds
    if payload.sync_policy is not None:
        next_policy = payload.sync_policy.model_dump(by_alias=True)
        if normalized_sync_policy(item.sync_policy_json) != next_policy:
            item.sync_policy_json = next_policy
            item.sync_policy_version = int(item.sync_policy_version or 1) + 1
    if payload.rate_limit_policy is not None:
        next_rate_policy = normalized_rate_limit_policy(
            item.rate_limit_policy_json
        )
        rate_aliases = {
            "visitor_check": "visitorCheck",
            "visitor_attempt": "visitorAttempt",
            "ip_start": "ipStart",
            "phone_attempt": "phoneAttempt",
            "channel_attempt": "channelAttempt",
            "status": "status",
            "cancel": "cancel",
        }
        for field_name in payload.rate_limit_policy.model_fields_set:
            next_rate_policy[rate_aliases[field_name]] = getattr(
                payload.rate_limit_policy, field_name
            ).model_dump(by_alias=True)
        item.rate_limit_policy_json = next_rate_policy
    wakeup_group_ids: set[int] = set()
    if (
        not marketing_was_enabled
        and item.marketing_enabled
        and item.online_enabled
    ):
        wakeup_group_ids.update(
            db.scalars(
                select(PersonalAccount.group_id)
                .where(
                    PersonalAccount.protocol_id == item.id,
                    PersonalAccount.group_id.is_not(None),
                    PersonalAccount.enabled.is_(True),
                    PersonalAccount.validation_status == "ready",
                    PersonalAccount.status.in_(("online_idle", "sending")),
                )
                .distinct()
            ).all()
        )
        for group_id in wakeup_group_ids:
            record_group_wakeup(
                db,
                group_id,
                reason="protocol_marketing_enabled",
            )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="节点名称已存在") from None
    for group_id in wakeup_group_ids:
        dispatch_group_wakeups_best_effort(group_id)
    return {
        "data": {
            "protocol": _row(
                db,
                item,
                definition=selected_definition,
            )
        }
    }


@router.delete("/{protocol_id}")
def delete_protocol_node(
    protocol_id: str,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    item = _node(db, protocol_id, current_user)
    account_count = int(
        db.scalar(
            select(func.count(PersonalAccount.id)).where(
                PersonalAccount.protocol_id == item.id,
            )
        )
        or 0
    )
    direct_channels = int(
        db.scalar(
            select(func.count(PromotionChannel.id)).where(
                PromotionChannel.protocol_node_id == item.id,
            )
        )
        or 0
    )
    pool_memberships = int(
        db.scalar(
            select(func.count(ProtocolPoolMember.id)).where(
                ProtocolPoolMember.protocol_node_id == item.id
            )
        )
        or 0
    )
    if account_count or direct_channels or pool_memberships:
        raise HTTPException(
            status_code=409,
            detail="协议仍有账号、渠道或协议池引用，请先解除引用；只需停用时请使用下线",
        )
    db.execute(
        delete(AccountMetadataSyncJob).where(
            AccountMetadataSyncJob.protocol_node_id == item.id
        )
    )
    db.execute(
        delete(AccountPairingAttempt).where(
            AccountPairingAttempt.protocol_node_id == item.id
        )
    )
    db.delete(item)
    db.commit()
    return {"data": {"ok": True}}


@router.get("/{protocol_id}/integration-spec")
def protocol_integration_spec(
    protocol_id: str,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    item = _node(db, protocol_id, current_user)
    pool_ids = select(ProtocolPoolMember.pool_id).where(
        ProtocolPoolMember.protocol_node_id == item.id,
        ProtocolPoolMember.enabled.is_(True),
    )
    channel_statement = select(PromotionChannel).where(
        (
            (PromotionChannel.protocol_node_id == item.id)
            | (PromotionChannel.protocol_pool_id.in_(pool_ids))
        ),
    )
    if current_user.role != "admin":
        channel_statement = channel_statement.where(
            PromotionChannel.created_by == current_user.id
        )
    channels = list(db.scalars(channel_statement.order_by(PromotionChannel.id)).all())
    return {
        "data": {
            "specVersion": "promotion-public-pairing/v1",
            "protocolId": entity_id(item),
            "protocolName": item.name,
            "important": "模板按渠道调用公共接口，不得写死协议 ID；渠道路由只影响新接入。",
            "runtime": {
                "configElementId": "promotion-runtime-config",
                "version": "promotion-browser-bridge/v2",
                "bridge": "window.PromotionBridge",
                "methods": {
                    "start": "submitPhone(phone, metadata)",
                    "status": "getPairingStatus(start.data.pairing)",
                    "cancel": "cancelPairing(start.data.pairing)",
                },
                "stableField": "pairingStartUrl",
            },
            "channels": [
                {
                    "id": entity_id(channel),
                    "name": channel.name,
                    "slug": channel.slug,
                    "status": channel.status,
                    "pairingStartUrl": (
                        f"/api/public/promotion/channels/{channel.slug}/pairing/start"
                    ),
                }
                for channel in channels
            ],
            "start": {
                "method": "POST",
                "pathTemplate": (
                    "/api/public/promotion/channels/{channelSlug}/pairing/start"
                ),
                "contentType": "text/plain;charset=UTF-8",
                "body": {
                    "phone": "15551234567",
                    "deviceFingerprint": "thumbmarkjs-or-fallback-value",
                    "metadata": {
                        "clientContext": {
                            "timeZone": "Europe/Berlin",
                            "viewport": [390, 844],
                            "screen": [390, 844],
                            "pixelRatio": 3,
                            "touchPoints": 5,
                        }
                    },
                },
                "responseFields": [
                    "pairingCode",
                    "attemptId",
                    "pairingStatus",
                    "expiresAt",
                    "statusUrl",
                    "cancelUrl",
                    "statusToken",
                    "statusTokenHeader",
                    "statusTokenScheme",
                ],
            },
            "status": {
                "method": "GET",
                "urlSource": "start.data.pairing.statusUrl",
                "tokenHeader": "Authorization",
                "tokenScheme": "Bearer",
                "states": [
                    "code_issued",
                    "waiting_phone",
                    "reconnecting",
                    "verified",
                    "failed",
                    "expired",
                    "cancelled",
                ],
                "successCondition": (
                    "pairingStatus === 'verified' && verified === true"
                ),
            },
            "cancel": {
                "method": "POST",
                "urlSource": "start.data.pairing.cancelUrl",
                "tokenHeader": "Authorization",
                "tokenScheme": "Bearer",
            },
            "rateLimit": {
                "source": "protocol-node",
                "policy": normalized_rate_limit_policy(
                    item.rate_limit_policy_json
                ),
                "response": {
                    "status": 429,
                    "code": "rate_limited",
                    "retryAfterHeader": "Retry-After",
                    "retryAfterField": "error.retryAfterSeconds",
                },
            },
            "rules": [
                "v2 模板必须通过 PromotionBridge 调用 start/status/cancel，不自行拼接鉴权头。",
                "只使用 start 返回的 statusUrl、cancelUrl 和 statusToken。",
                "linked_offline 不是配对成功，模板只认 verified 终态。",
                "令牌只能按 Bearer 方案放在 Authorization 请求头，不能放进 URL。",
                "收到 429 时按 Retry-After 等待；模板不得自行提高轮询频率。",
                "用户可见号码不得显示前导加号。",
            ],
        }
    }


def _batch(
    payload: ProtocolBatchAction,
    db: DbSession,
    user,
    *,
    online: bool,
) -> dict:
    items = list(
        db.scalars(
            _scope(
                select(ProtocolNode).where(
                    identifiers_filter(ProtocolNode, payload.protocol_ids),
                ),
                user,
            )
        ).all()
    )
    if any(
        not any(matches_identifier(item, requested) for item in items)
        for requested in set(payload.protocol_ids)
    ):
        raise HTTPException(status_code=404, detail="部分协议不存在")

    errors: list[dict] = []
    affected_accounts = 0
    wakeup_group_ids: set[int] = set()
    client = WaGatewayClient()
    for item in items:
        capacity = protocol_capacity(db, item)
        remaining_online = (
            None
            if item.max_online_accounts is None
            else max(item.max_online_accounts - capacity.online_accounts, 0)
        )
        accounts = list(
            db.scalars(
                select(PersonalAccount).where(
                    PersonalAccount.protocol_id == item.id,
                    PersonalAccount.enabled.is_(True),
                )
            ).all()
        )
        item.online_enabled = online
        for account in accounts:
            if online and account.status in {"unpaired", "pairing", "disabled"}:
                continue
            already_online = account.status in _ONLINE_STATES
            if online and not already_online and remaining_online == 0:
                errors.append(
                    {
                        "protocolId": entity_id(item),
                        "accountId": str(account.id),
                        "error": "协议节点在线账号已达到上限",
                    }
                )
                continue
            try:
                result = (
                    (
                        client.connect(account.gateway_account_id)
                        if already_online
                        else client.connect(
                            account.gateway_account_id,
                            _account_proxy_url(db, account.gateway_account_id),
                        )
                    )
                    if online
                    else client.disconnect(account.gateway_account_id)
                )
                state = str(result.get("state") or "")
                if state:
                    account.status = state
                if (
                    online
                    and account.group_id is not None
                    and account.validation_status == "ready"
                    and account.status in {"online_idle", "sending"}
                    and item.marketing_enabled
                ):
                    wakeup_group_ids.add(account.group_id)
                affected_accounts += 1
                if online and not already_online and remaining_online is not None:
                    remaining_online = max(remaining_online - 1, 0)
            except GatewayError as exc:
                errors.append(
                    {
                        "protocolId": entity_id(item),
                        "accountId": str(account.id),
                        "error": _safe_gateway_error(exc),
                    }
                )
    if online:
        for group_id in wakeup_group_ids:
            record_group_wakeup(
                db,
                group_id,
                reason="protocol_online_enabled",
            )
    db.commit()
    for group_id in wakeup_group_ids:
        dispatch_group_wakeups_best_effort(group_id)
    return {
        "data": {
            "requestedCount": len(payload.protocol_ids),
            "updatedCount": len(items),
            "affectedAccounts": affected_accounts,
            "failedCount": len(errors),
            "errors": errors,
        }
    }


@router.post("/batch-online")
@router.post("/batch-connect")
def batch_online(
    payload: ProtocolBatchAction, db: DbSession, current_user: CurrentUser
) -> dict:
    return _batch(payload, db, current_user, online=True)


@router.post("/batch-offline")
@router.post("/batch-disconnect")
def batch_offline(
    payload: ProtocolBatchAction, db: DbSession, current_user: CurrentUser
) -> dict:
    return _batch(payload, db, current_user, online=False)


def _pool_scope(statement, user):
    return (
        statement
        if user.role == "admin"
        else statement.where(ProtocolPool.created_by == user.id)
    )


def _pool(db: DbSession, identifier: str, user) -> ProtocolPool:
    item = db.scalar(
        _pool_scope(
            select(ProtocolPool).where(
                identifier_filter(ProtocolPool, identifier),
            ),
            user,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="协议池不存在")
    return item


def _pool_row(db: DbSession, item: ProtocolPool) -> dict:
    members = list(
        db.execute(
            select(ProtocolPoolMember, ProtocolNode)
            .join(
                ProtocolNode,
                ProtocolNode.id == ProtocolPoolMember.protocol_node_id,
            )
            .where(ProtocolPoolMember.pool_id == item.id)
            .order_by(ProtocolPoolMember.priority, ProtocolPoolMember.id)
        ).all()
    )
    return {
        "id": entity_id(item),
        "name": item.name,
        "remark": item.remark,
        "members": [
            {
                "id": str(member.id),
                "protocolNodeId": entity_id(node),
                "protocolNodeName": node.name,
                "priority": member.priority,
                "enabled": member.enabled,
                "available": (
                    member.enabled
                    and ingress_unavailable_reason(
                        node, protocol_capacity(db, node)
                    )
                    is None
                ),
            }
            for member, node in members
        ],
        "createdAt": item.created_at.isoformat(),
        "updatedAt": item.updated_at.isoformat(),
    }


def _replace_pool_members(db: DbSession, item: ProtocolPool, members) -> None:
    node_ids = [int(member.protocol_node_id) for member in members]
    nodes = list(
        db.scalars(
            select(ProtocolNode).where(
                ProtocolNode.id.in_(node_ids) if node_ids else False,
                ProtocolNode.created_by == item.created_by,
            )
        ).all()
    )
    if len(nodes) != len(node_ids):
        raise HTTPException(status_code=404, detail="部分协议池成员节点不存在")
    existing = list(
        db.scalars(
            select(ProtocolPoolMember).where(
                ProtocolPoolMember.pool_id == item.id
            )
        ).all()
    )
    for member in existing:
        db.delete(member)
    db.flush()
    for member in members:
        db.add(
            ProtocolPoolMember(
                pool_id=item.id,
                protocol_node_id=int(member.protocol_node_id),
                priority=member.priority,
                enabled=member.enabled,
            )
        )


@pool_router.get("")
def list_protocol_pools(db: DbSession, current_user: CurrentUser) -> dict:
    items = list(
        db.scalars(
            _pool_scope(
                select(ProtocolPool),
                current_user,
            ).order_by(ProtocolPool.id)
        ).all()
    )
    return {
        "data": {"rows": [_pool_row(db, item) for item in items], "total": len(items)}
    }


@pool_router.post("", status_code=status.HTTP_201_CREATED)
def create_protocol_pool(
    payload: ProtocolPoolCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    item = ProtocolPool(
        public_id=new_public_id("ppool"),
        name=payload.name,
        remark=payload.remark,
        created_by=current_user.id,
    )
    db.add(item)
    try:
        db.flush()
        _replace_pool_members(db, item, payload.members)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="协议池名称或成员已存在") from None
    db.refresh(item)
    return {"data": {"pool": _pool_row(db, item)}}


@pool_router.patch("/{pool_id}")
def update_protocol_pool(
    pool_id: str,
    payload: ProtocolPoolUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    item = _pool(db, pool_id, current_user)
    if payload.name is not None:
        item.name = payload.name
    if "remark" in payload.model_fields_set:
        item.remark = payload.remark
    if payload.members is not None:
        _replace_pool_members(db, item, payload.members)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="协议池名称或成员已存在") from None
    return {"data": {"pool": _pool_row(db, item)}}


@pool_router.delete("/{pool_id}")
def delete_protocol_pool(
    pool_id: str,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    item = _pool(db, pool_id, current_user)
    channel_count = int(
        db.scalar(
            select(func.count(PromotionChannel.id)).where(
                PromotionChannel.protocol_pool_id == item.id,
            )
        )
        or 0
    )
    if channel_count:
        raise HTTPException(status_code=409, detail="协议池仍被推广渠道使用")
    db.delete(item)
    db.commit()
    return {"data": {"ok": True}}
