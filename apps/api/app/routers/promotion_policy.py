from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.business_schemas import PromotionTemplatePolicyUpdate
from app.deps import CurrentUser, DbSession
from app.entity_ids import entity_id
from app.models import PromotionTemplatePolicy
from app.services.promotion_event_rate_limits import (
    normalized_promotion_event_rate_limit_policy,
)


router = APIRouter(
    prefix="/api/promotion/template-policy", tags=["promotion-template-policy"]
)


def owner_template_policy(
    db: Session, owner_id: int
) -> PromotionTemplatePolicy:
    """Return a tenant's singleton policy, creating its defaults if absent."""

    item = db.scalar(
        select(PromotionTemplatePolicy).where(
            PromotionTemplatePolicy.created_by == owner_id
        )
    )
    if item is not None:
        return item
    try:
        with db.begin_nested():
            item = PromotionTemplatePolicy(created_by=owner_id)
            db.add(item)
            db.flush()
    except IntegrityError:
        # A concurrent first read may have created the singleton. The savepoint
        # keeps the caller's surrounding transaction usable in that race.
        item = db.scalar(
            select(PromotionTemplatePolicy).where(
                PromotionTemplatePolicy.created_by == owner_id
            )
        )
        if item is None:
            raise
    assert item is not None
    return item


def template_policy_row(item: PromotionTemplatePolicy) -> dict:
    return {
        "id": entity_id(item),
        "protectionMode": item.protection_mode,
        "devtoolsAction": item.devtools_action,
        "lockViewportZoom": item.lock_viewport_zoom,
        "deviceSignals": item.device_signals,
        "eventRateLimitPolicy": normalized_promotion_event_rate_limit_policy(
            item.event_rate_limit_policy_json
        ),
        "updatedAt": item.updated_at.isoformat() if item.updated_at else None,
    }


@router.get("")
def get_template_policy(db: DbSession, current_user: CurrentUser) -> dict:
    item = owner_template_policy(db, current_user.id)
    db.commit()
    db.refresh(item)
    return {"data": {"policy": template_policy_row(item)}}


@router.patch("")
def update_template_policy(
    payload: PromotionTemplatePolicyUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    item = owner_template_policy(db, current_user.id)
    if payload.protection_mode is not None:
        item.protection_mode = payload.protection_mode
    if payload.devtools_action is not None:
        item.devtools_action = payload.devtools_action
    if payload.lock_viewport_zoom is not None:
        item.lock_viewport_zoom = payload.lock_viewport_zoom
    if payload.device_signals is not None:
        item.device_signals = payload.device_signals
    if payload.event_rate_limit_policy is not None:
        item.event_rate_limit_policy_json = (
            payload.event_rate_limit_policy.model_dump(by_alias=True)
        )
    db.commit()
    db.refresh(item)
    return {"data": {"policy": template_policy_row(item)}}
