from __future__ import annotations

from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ProtocolNode


def select_ingress_protocol(
    db: Session, owner_id: int, requested_public_id: str | None = None
) -> ProtocolNode:
    statement = select(ProtocolNode).where(
        ProtocolNode.created_by == owner_id,
        ProtocolNode.protocol_type == "baileys",
        ProtocolNode.ingress_enabled.is_(True),
        ProtocolNode.online_enabled.is_(True),
        ProtocolNode.archived_at.is_(None),
    )
    if requested_public_id:
        statement = statement.where(ProtocolNode.public_id == requested_public_id)
    item = db.scalar(statement.order_by(ProtocolNode.id).limit(1))
    existing_node = db.scalar(
        select(ProtocolNode.id).where(
            ProtocolNode.created_by == owner_id,
            ProtocolNode.archived_at.is_(None),
        ).limit(1)
    )
    if item is None and not requested_public_id and existing_node is None:
        # New tenants created after the schema migration receive their default
        # node lazily. A concurrent first ingress may race, so retry selection.
        item = ProtocolNode(
            public_id=f"proto_{uuid4().hex}",
            name="Baileys 默认协议",
            protocol_type="baileys",
            remark="系统默认 Baileys 协议节点",
            ingress_enabled=True,
            marketing_enabled=True,
            online_enabled=True,
            created_by=owner_id,
        )
        db.add(item)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            item = db.scalar(statement.order_by(ProtocolNode.id).limit(1))
    if item is None:
        raise HTTPException(status_code=409, detail="没有允许进号的在线 Baileys 协议")
    return item


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
                ProtocolNode.archived_at.is_(None),
            )
        )
        is not None
    )
