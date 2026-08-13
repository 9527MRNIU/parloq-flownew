from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.business_schemas import ProtocolBatchAction, ProtocolNodeUpdate
from app.deps import CurrentUser, DbSession
from app.models import PersonalAccount, ProtocolNode
from app.services.protocol_nodes import select_ingress_protocol
from app.services.wa_gateway import GatewayError, WaGatewayClient


router = APIRouter(prefix="/api/protocol-nodes", tags=["protocol-nodes"])

_ONLINE_STATES = {"warming", "online_idle", "sending", "draining"}
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


def _node(db: DbSession, public_id: str, user) -> ProtocolNode:
    item = db.scalar(
        _scope(
            select(ProtocolNode).where(
                ProtocolNode.public_id == public_id,
                ProtocolNode.archived_at.is_(None),
            ),
            user,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="协议不存在")
    return item


def _row(db: DbSession, item: ProtocolNode) -> dict:
    account_states = list(
        db.execute(
            select(PersonalAccount.status, PersonalAccount.validation_status).where(
                PersonalAccount.protocol_id == item.id,
                PersonalAccount.archived_at.is_(None),
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
    return {
        "id": item.public_id,
        "publicId": item.public_id,
        "name": item.name,
        "protocol": item.protocol_type,
        "remark": item.remark,
        "ingressEnabled": item.ingress_enabled,
        "marketingEnabled": item.marketing_enabled,
        "online": item.online_enabled,
        "accountTotal": total,
        "validAccounts": valid,
        "onlineAccounts": online,
        "validRate": round(valid / total * 100, 2) if total else None,
        "onlineRate": round(online / valid * 100, 2) if valid else None,
    }


@router.get("")
def list_protocol_nodes(db: DbSession, current_user: CurrentUser) -> dict:
    owner_has_node = db.scalar(
        select(ProtocolNode.id).where(
            ProtocolNode.created_by == current_user.id,
            ProtocolNode.archived_at.is_(None),
        ).limit(1)
    )
    if current_user.role != "admin" and owner_has_node is None:
        select_ingress_protocol(db, current_user.id)
        db.commit()
    statement = _scope(
        select(ProtocolNode).where(ProtocolNode.archived_at.is_(None)), current_user
    )
    items = db.scalars(statement.order_by(ProtocolNode.id)).all()
    return {"data": {"rows": [_row(db, item) for item in items], "total": len(items)}}


@router.patch("/{public_id}")
def update_protocol_node(
    public_id: str,
    payload: ProtocolNodeUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    item = _node(db, public_id, current_user)
    if payload.name is not None:
        item.name = payload.name
    if "remark" in payload.model_fields_set:
        item.remark = payload.remark
    if payload.ingress_enabled is not None:
        item.ingress_enabled = payload.ingress_enabled
    if payload.marketing_enabled is not None:
        item.marketing_enabled = payload.marketing_enabled
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="协议名称已存在") from None
    return {"data": {"protocol": _row(db, item)}}


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
                    ProtocolNode.public_id.in_(payload.protocol_ids),
                    ProtocolNode.archived_at.is_(None),
                ),
                user,
            )
        ).all()
    )
    if {item.public_id for item in items} != set(payload.protocol_ids):
        raise HTTPException(status_code=404, detail="部分协议不存在")

    errors: list[dict] = []
    affected_accounts = 0
    client = WaGatewayClient()
    for item in items:
        accounts = list(
            db.scalars(
                select(PersonalAccount).where(
                    PersonalAccount.protocol_id == item.id,
                    PersonalAccount.archived_at.is_(None),
                    PersonalAccount.enabled.is_(True),
                )
            ).all()
        )
        item.online_enabled = online
        for account in accounts:
            if online and account.status in {"unpaired", "pairing", "disabled"}:
                continue
            try:
                result = (
                    client.connect(account.public_id)
                    if online
                    else client.disconnect(account.public_id)
                )
                state = str(result.get("state") or "")
                if state:
                    account.status = state
                affected_accounts += 1
            except GatewayError as exc:
                errors.append(
                    {
                        "protocolId": item.public_id,
                        "accountId": account.public_id,
                        "error": _safe_gateway_error(exc),
                    }
                )
    db.commit()
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
