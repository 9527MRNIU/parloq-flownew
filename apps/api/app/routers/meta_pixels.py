from __future__ import annotations


from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.deps import CurrentUser, DbSession
from app.entity_ids import identifier_filter
from app.snowflake import new_public_id

from app.models import MetaConversionDelivery, MetaPixel, PromotionChannel
from app.schemas import MetaPixelCreate, MetaPixelUpdate
from app.security import encrypt_secret
from app.serializers import meta_pixel_row


router = APIRouter(prefix="/api/meta-pixels", tags=["meta-pixels"])


def _reset_domain_monitoring(db: DbSession, pixel_id: int) -> None:
    channels = db.scalars(
        select(PromotionChannel).where(
            PromotionChannel.pixel_id == pixel_id,
        )
    ).all()
    for channel in channels:
        channel.meta_domain_blocked = False
        channel.meta_domain_blocked_at = None


def _pixel_or_404(db: DbSession, identifier: str, user) -> MetaPixel:
    statement = select(MetaPixel).where(
        identifier_filter(MetaPixel, identifier),
    )
    if user.role != "admin":
        statement = statement.where(MetaPixel.created_by == user.id)
    pixel = db.scalar(statement)
    if pixel is None:
        raise HTTPException(status_code=404, detail="Meta Pixel 不存在")
    return pixel


@router.get("")
def list_pixels(db: DbSession, current_user: CurrentUser) -> dict:
    statement = select(MetaPixel)
    if current_user.role != "admin":
        statement = statement.where(MetaPixel.created_by == current_user.id)
    pixels = db.scalars(statement.order_by(MetaPixel.created_at.desc())).all()
    rows = [meta_pixel_row(pixel) for pixel in pixels]
    return {"data": {"rows": rows, "total": len(rows)}}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_pixel(payload: MetaPixelCreate, db: DbSession, current_user: CurrentUser) -> dict:
    token = (payload.capi_token or "").strip()
    if payload.capi_enabled and not token:
        raise HTTPException(status_code=422, detail="启用 Meta CAPI 前必须配置 CAPI Token")
    pixel = MetaPixel(
        public_id=new_public_id("pxl"),
        name=payload.name,
        dataset_id=payload.dataset_id,
        capi_token_ciphertext=encrypt_secret(token) if token else None,
        capi_token_last4=token[-4:] if token else "",
        browser_pixel_enabled=payload.browser_pixel_enabled,
        capi_enabled=payload.capi_enabled,
        event_mapping_json=payload.event_mapping,
        enabled=payload.enabled,
        created_by=current_user.id,
    )
    db.add(pixel)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Pixel / Dataset ID 已存在") from None
    db.refresh(pixel)
    return {"data": {"pixel": meta_pixel_row(pixel)}}


@router.patch("/{pixel_id}")
def update_pixel(
    pixel_id: str,
    payload: MetaPixelUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    pixel = _pixel_or_404(db, pixel_id, current_user)
    monitoring_config_changed = False
    if payload.name is not None:
        pixel.name = payload.name
    if payload.dataset_id is not None:
        monitoring_config_changed = pixel.dataset_id != payload.dataset_id
        pixel.dataset_id = payload.dataset_id
    if payload.enabled is not None:
        monitoring_config_changed = (
            monitoring_config_changed or pixel.enabled != payload.enabled
        )
        pixel.enabled = payload.enabled
    if payload.browser_pixel_enabled is not None:
        monitoring_config_changed = (
            monitoring_config_changed
            or pixel.browser_pixel_enabled != payload.browser_pixel_enabled
        )
        pixel.browser_pixel_enabled = payload.browser_pixel_enabled
    if payload.event_mapping is not None:
        pixel.event_mapping_json = payload.event_mapping
    if "capi_token" in payload.model_fields_set:
        token = (payload.capi_token or "").strip()
        pixel.capi_token_ciphertext = encrypt_secret(token) if token else None
        pixel.capi_token_last4 = token[-4:] if token else ""
        if not token:
            pixel.capi_enabled = False
    if payload.capi_enabled is not None:
        pixel.capi_enabled = payload.capi_enabled
    if pixel.capi_enabled and not pixel.capi_token_ciphertext:
        raise HTTPException(status_code=422, detail="启用 Meta CAPI 前必须配置 CAPI Token")
    if monitoring_config_changed:
        _reset_domain_monitoring(db, pixel.id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Pixel / Dataset ID 已存在") from None
    db.refresh(pixel)
    return {"data": {"pixel": meta_pixel_row(pixel)}}


@router.delete("/{pixel_id}")
def delete_pixel(pixel_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    pixel = _pixel_or_404(db, pixel_id, current_user)
    _reset_domain_monitoring(db, pixel.id)
    db.execute(
        delete(MetaConversionDelivery).where(
            MetaConversionDelivery.pixel_id == pixel.id
        )
    )
    db.delete(pixel)
    db.commit()
    return {"data": {"ok": True}}
