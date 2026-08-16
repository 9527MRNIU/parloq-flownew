from __future__ import annotations


from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.deps import CurrentUser, DbSession
from app.entity_ids import identifier_filter
from app.snowflake import new_public_id

from app.models import MetaPixel
from app.schemas import MetaPixelCreate, MetaPixelUpdate
from app.security import encrypt_secret, utcnow
from app.serializers import meta_pixel_row


router = APIRouter(prefix="/api/meta-pixels", tags=["meta-pixels"])


def _pixel_or_404(db: DbSession, identifier: str, user) -> MetaPixel:
    statement = select(MetaPixel).where(
        identifier_filter(MetaPixel, identifier),
        MetaPixel.archived_at.is_(None),
    )
    if user.role != "admin":
        statement = statement.where(MetaPixel.created_by == user.id)
    pixel = db.scalar(statement)
    if pixel is None:
        raise HTTPException(status_code=404, detail="Meta Pixel 不存在")
    return pixel


@router.get("")
def list_pixels(db: DbSession, current_user: CurrentUser) -> dict:
    statement = select(MetaPixel).where(MetaPixel.archived_at.is_(None))
    if current_user.role != "admin":
        statement = statement.where(MetaPixel.created_by == current_user.id)
    pixels = db.scalars(statement.order_by(MetaPixel.created_at.desc())).all()
    rows = [meta_pixel_row(pixel) for pixel in pixels]
    return {"data": {"rows": rows, "total": len(rows)}}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_pixel(payload: MetaPixelCreate, db: DbSession, current_user: CurrentUser) -> dict:
    token = (payload.capi_token or "").strip()
    pixel = MetaPixel(
        public_id=new_public_id("pxl"),
        name=payload.name,
        dataset_id=payload.dataset_id,
        capi_token_ciphertext=encrypt_secret(token) if token else None,
        capi_token_last4=token[-4:] if token else "",
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
    if payload.name is not None:
        pixel.name = payload.name
    if payload.dataset_id is not None:
        pixel.dataset_id = payload.dataset_id
    if payload.enabled is not None:
        pixel.enabled = payload.enabled
    if "capi_token" in payload.model_fields_set:
        token = (payload.capi_token or "").strip()
        pixel.capi_token_ciphertext = encrypt_secret(token) if token else None
        pixel.capi_token_last4 = token[-4:] if token else ""
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Pixel / Dataset ID 已存在") from None
    db.refresh(pixel)
    return {"data": {"pixel": meta_pixel_row(pixel)}}


@router.delete("/{pixel_id}")
def archive_pixel(pixel_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    pixel = _pixel_or_404(db, pixel_id, current_user)
    pixel.enabled = False
    pixel.archived_at = utcnow()
    db.commit()
    return {"data": {"ok": True}}
