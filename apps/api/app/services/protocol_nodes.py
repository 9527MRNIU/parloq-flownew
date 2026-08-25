from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.entity_ids import identifier_filter
from app.models import (
    AccountPairingAttempt,
    PersonalAccount,
    PromotionChannel,
    ProtocolDefinition,
    ProtocolNode,
    ProtocolPool,
    ProtocolPoolMember,
)
from app.security import utcnow
from app.snowflake import new_public_id


DEFAULT_SYNC_POLICY: dict[str, bool] = {
    "closeOnline": True,
    "avatar": True,
    "groupDetails": True,
    "contacts": True,
}

DEFAULT_RATE_LIMIT_POLICY: dict[str, dict[str, int | None]] = {
    "visitorCheck": {"maxRequests": 5, "windowSeconds": 600},
    "visitorAttempt": {"maxRequests": 5, "windowSeconds": 600},
    "ipStart": {"maxRequests": 5, "windowSeconds": 600},
    "phoneAttempt": {"maxRequests": 5, "windowSeconds": 600},
    "channelAttempt": {"maxRequests": None, "windowSeconds": 60},
    "status": {"maxRequests": 60, "windowSeconds": 60},
    "cancel": {"maxRequests": 5, "windowSeconds": 600},
}

ONLINE_ACCOUNT_STATES = {"warming", "online_idle", "sending", "draining"}
ACTIVE_PAIRING_STATUSES = {
    "code_issued",
    "waiting_phone",
    "reconnecting",
}


@dataclass(frozen=True)
class ProtocolCapacity:
    total_accounts: int
    online_accounts: int
    active_pairings: int


@dataclass(frozen=True)
class ProtocolRuntimeBinding:
    definition_id: str
    version: str


def protocol_runtime_binding(
    db: Session, item: ProtocolNode
) -> ProtocolRuntimeBinding:
    definition = db.get(ProtocolDefinition, item.protocol_definition_id)
    if definition is None or not definition.enabled:
        raise HTTPException(status_code=409, detail="协议定义不存在或已停用")
    if definition.build_status != "ready":
        raise HTTPException(status_code=409, detail="协议尚未构建完成，暂不能接入账号")
    return ProtocolRuntimeBinding(str(definition.id), definition.version)


def normalized_sync_policy(value: dict | None) -> dict[str, bool]:
    source = value if isinstance(value, dict) else {}
    result = dict(DEFAULT_SYNC_POLICY)
    snake_aliases = {
        "closeOnline": "close_online",
        "groupDetails": "group_details",
    }
    for key in result:
        raw = source.get(key, source.get(snake_aliases.get(key, "")))
        if isinstance(raw, bool):
            result[key] = raw
    if not isinstance(
        source.get("groupDetails", source.get("group_details")), bool
    ):
        legacy_summary = source.get(
            "groupSummary", source.get("group_summary")
        )
        if isinstance(legacy_summary, bool):
            result["groupDetails"] = legacy_summary
    return result


def normalized_rate_limit_policy(
    value: dict | None,
) -> dict[str, dict[str, int | None]]:
    source = value if isinstance(value, dict) else {}
    snake_aliases = {
        "visitorCheck": "visitor_check",
        "visitorAttempt": "visitor_attempt",
        "ipStart": "ip_start",
        "phoneAttempt": "phone_attempt",
        "channelAttempt": "channel_attempt",
    }
    result: dict[str, dict[str, int | None]] = {}
    for key, defaults in DEFAULT_RATE_LIMIT_POLICY.items():
        raw = source.get(key, source.get(snake_aliases.get(key, ""), {}))
        rule = raw if isinstance(raw, dict) else {}
        max_requests = rule.get("maxRequests", rule.get("max_requests"))
        window_seconds = rule.get("windowSeconds", rule.get("window_seconds"))
        result[key] = {
            "maxRequests": (
                max_requests
                if isinstance(max_requests, int)
                and not isinstance(max_requests, bool)
                and max_requests > 0
                else defaults["maxRequests"]
            ),
            "windowSeconds": (
                window_seconds
                if isinstance(window_seconds, int)
                and not isinstance(window_seconds, bool)
                and window_seconds > 0
                else defaults["windowSeconds"]
            ),
        }
    return result


def protocol_capacity(db: Session, item: ProtocolNode) -> ProtocolCapacity:
    total = int(
        db.scalar(
            select(func.count(PersonalAccount.id)).where(
                PersonalAccount.protocol_id == item.id,
                PersonalAccount.admission_status.in_(("reserved", "active")),
                PersonalAccount.deleted_at.is_(None),
            )
        )
        or 0
    )
    online = int(
        db.scalar(
            select(func.count(PersonalAccount.id)).where(
                PersonalAccount.protocol_id == item.id,
                PersonalAccount.status.in_(ONLINE_ACCOUNT_STATES),
                PersonalAccount.admission_status == "active",
                PersonalAccount.deleted_at.is_(None),
            )
        )
        or 0
    )
    pairings = int(
        db.scalar(
            select(func.count(AccountPairingAttempt.id)).where(
                AccountPairingAttempt.protocol_node_id == item.id,
                AccountPairingAttempt.status.in_(ACTIVE_PAIRING_STATUSES),
                AccountPairingAttempt.expires_at > utcnow(),
            )
        )
        or 0
    )
    return ProtocolCapacity(total, online, pairings)


def ingress_unavailable_reason(
    item: ProtocolNode,
    capacity: ProtocolCapacity,
) -> str | None:
    if not item.online_enabled:
        return "协议节点已下线"
    if not item.ingress_enabled:
        return "协议节点已关闭进号"
    if (
        item.max_account_count is not None
        and capacity.total_accounts >= item.max_account_count
    ):
        return "协议节点账号总量已达到上限"
    if (
        item.max_online_accounts is not None
        and capacity.online_accounts >= item.max_online_accounts
    ):
        return "协议节点在线账号已达到上限"
    if (
        item.max_concurrent_pairings is not None
        and capacity.active_pairings >= item.max_concurrent_pairings
    ):
        return "协议节点并发配对已达到上限"
    return None


def protocol_health(db: Session, item: ProtocolNode) -> tuple[str, str | None]:
    capacity = protocol_capacity(db, item)
    reason = ingress_unavailable_reason(item, capacity)
    if reason is None:
        return "available", None
    if "上限" in reason:
        return "capacity_limited", reason
    return "offline", reason


def default_protocol_definition(db: Session) -> ProtocolDefinition:
    item = db.scalar(
        select(ProtocolDefinition)
        .where(
            ProtocolDefinition.adapter_key == "baileys",
            ProtocolDefinition.build_status == "ready",
            ProtocolDefinition.enabled.is_(True),
        )
        .order_by(
            ProtocolDefinition.is_builtin.desc(),
            ProtocolDefinition.id,
        )
        .limit(1)
    )
    if item is None:
        raise HTTPException(status_code=409, detail="当前没有可用的协议定义")
    return item


def _new_default_node(
    owner_id: int,
    definition: ProtocolDefinition,
) -> ProtocolNode:
    return ProtocolNode(
        public_id=new_public_id("proto"),
        name="默认节点",
        protocol_type=definition.adapter_key,
        protocol_definition_id=definition.id,
        remark="系统默认 Baileys 协议节点",
        ingress_enabled=True,
        marketing_enabled=True,
        online_enabled=True,
        max_account_count=None,
        max_online_accounts=1000,
        max_concurrent_pairings=None,
        connection_policy="on_demand",
        idle_disconnect_seconds=600,
        post_verify_grace_seconds=120,
        sync_policy_version=1,
        sync_policy_json=dict(DEFAULT_SYNC_POLICY),
        rate_limit_policy_json={
            key: dict(rule) for key, rule in DEFAULT_RATE_LIMIT_POLICY.items()
        },
        created_by=owner_id,
    )


def select_ingress_protocol(
    db: Session, owner_id: int, requested_public_id: str | None = None
) -> ProtocolNode:
    statement = select(ProtocolNode).where(
        ProtocolNode.created_by == owner_id,
    )
    if requested_public_id:
        statement = statement.where(
            identifier_filter(ProtocolNode, requested_public_id)
        )
    else:
        statement = statement.where(ProtocolNode.protocol_type == "baileys")
    item = db.scalar(
        statement.order_by(ProtocolNode.id).limit(1).with_for_update()
    )
    if item is None and not requested_public_id:
        existing_node = db.scalar(
            select(ProtocolNode.id).where(
                ProtocolNode.created_by == owner_id,
            ).limit(1)
        )
        if existing_node is None:
            item = _new_default_node(
                owner_id,
                default_protocol_definition(db),
            )
            try:
                with db.begin_nested():
                    db.add(item)
                    db.flush()
            except IntegrityError:
                item = db.scalar(
                    statement.order_by(ProtocolNode.id).limit(1).with_for_update()
                )
    if item is None:
        raise HTTPException(status_code=409, detail="没有可用的协议节点")
    reason = ingress_unavailable_reason(item, protocol_capacity(db, item))
    if reason:
        raise HTTPException(
            status_code=409,
            detail=f"所选协议节点当前不可用于进号：{reason}",
        )
    return item


def resolve_channel_ingress_protocol(
    db: Session,
    channel: PromotionChannel,
) -> ProtocolNode:
    """Resolve and lock a new attempt's node; direct routes never auto-fallback."""

    if channel.protocol_node_id is not None:
        item = db.scalar(
            select(ProtocolNode)
            .where(
                ProtocolNode.id == channel.protocol_node_id,
                ProtocolNode.created_by == channel.created_by,
            )
            .with_for_update()
        )
        if item is None:
            raise HTTPException(status_code=409, detail="渠道绑定的协议节点不存在")
        reason = ingress_unavailable_reason(item, protocol_capacity(db, item))
        if reason:
            raise HTTPException(status_code=409, detail=reason)
        return item

    if channel.protocol_pool_id is not None:
        pool = db.scalar(
            select(ProtocolPool).where(
                ProtocolPool.id == channel.protocol_pool_id,
                ProtocolPool.created_by == channel.created_by,
            )
        )
        if pool is None:
            raise HTTPException(status_code=409, detail="渠道绑定的协议池不存在")
        candidates = list(
            db.scalars(
                select(ProtocolNode)
                .join(
                    ProtocolPoolMember,
                    ProtocolPoolMember.protocol_node_id == ProtocolNode.id,
                )
                .where(
                    ProtocolPoolMember.pool_id == pool.id,
                    ProtocolPoolMember.enabled.is_(True),
                    ProtocolNode.created_by == channel.created_by,
                )
                .order_by(ProtocolPoolMember.priority, ProtocolPoolMember.id)
                .with_for_update()
            ).all()
        )
        for item in candidates:
            if ingress_unavailable_reason(item, protocol_capacity(db, item)) is None:
                return item
        raise HTTPException(status_code=409, detail="协议池中没有可接入的协议节点")

    # Compatibility for channels created before route fields existed. Once
    # resolved, persist the direct route so subsequent changes are explicit.
    item = select_ingress_protocol(db, channel.created_by)
    channel.protocol_node_id = item.id
    channel.protocol_pool_id = None
    channel.route_version = max(int(channel.route_version or 1), 1)
    return item


def channel_rate_limit_protocol(
    db: Session,
    channel: PromotionChannel,
) -> ProtocolNode:
    """Return the configured node whose policy protects a start preflight.

    Pool routes use their first enabled member for the preflight. The final
    selected member applies its own attempt-creation limits after routing.
    """

    if channel.protocol_node_id is not None:
        item = db.get(ProtocolNode, channel.protocol_node_id)
        if item is not None and item.created_by == channel.created_by:
            return item
        raise HTTPException(status_code=409, detail="渠道绑定的协议节点不存在")
    if channel.protocol_pool_id is not None:
        item = db.scalar(
            select(ProtocolNode)
            .join(
                ProtocolPoolMember,
                ProtocolPoolMember.protocol_node_id == ProtocolNode.id,
            )
            .where(
                ProtocolPoolMember.pool_id == channel.protocol_pool_id,
                ProtocolPoolMember.enabled.is_(True),
                ProtocolNode.created_by == channel.created_by,
            )
            .order_by(ProtocolPoolMember.priority, ProtocolPoolMember.id)
            .limit(1)
        )
        if item is not None:
            return item
        raise HTTPException(status_code=409, detail="协议池中没有可用的协议节点配置")
    return select_ingress_protocol(db, channel.created_by)


def marketing_protocol_available(db: Session, protocol_id: int | None) -> bool:
    if protocol_id is None:
        return False
    return (
        db.scalar(
            select(ProtocolNode.id).where(
                ProtocolNode.id == protocol_id,
                ProtocolNode.protocol_type == "baileys",
                ProtocolNode.marketing_enabled.is_(True),
                ProtocolNode.online_enabled.is_(True),
            )
        )
        is not None
    )
