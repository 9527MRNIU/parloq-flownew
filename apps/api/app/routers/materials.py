from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, Response, UploadFile
from sqlalchemy import func, select

from app.business_schemas import MaterialCreate, MaterialUpdate
from app.deps import CurrentUser, DbSession
from app.entity_ids import entity_id, identifier_filter
from app.material_files import (
    BINARY_MATERIAL_TYPES,
    read_material_upload,
    safe_filename,
    verify_material_access_token,
)
from app.models import HyperlinkTemplate, Material
from app.message_capabilities import (
    TEXT_MATERIAL_ROLES,
    TEXT_ROLE_LABELS,
    TEXT_ROLE_LIMITS,
    normalize_text_role,
    validate_text_material_content,
)
from app.serializers import iso
from app.snowflake import new_public_id


router = APIRouter(prefix="/api/materials", tags=["materials"])
legacy_router = APIRouter(
    prefix="/api/hyperlink/materials",
    tags=["materials-compatibility"],
    include_in_schema=False,
)
internal_router = APIRouter(
    prefix="/api/internal/materials",
    tags=["materials-internal"],
    include_in_schema=False,
)


def _one(db: DbSession, identifier: str, current_user) -> Material:
    statement = select(Material).where(
        identifier_filter(Material, identifier),
    )
    if current_user.role != "admin":
        statement = statement.where(Material.created_by == current_user.id)
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    return item


def material_row(item: Material) -> dict:
    return {
        "id": entity_id(item),
        "name": item.name,
        "type": item.material_type,
        "textRole": item.text_role if item.material_type == "text" else None,
        "contentJson": (
            {} if item.material_type in BINARY_MATERIAL_TYPES else item.content_json
        ),
        "fileName": item.file_name,
        "contentType": item.content_type,
        "size": item.file_size,
        "sha256": item.file_sha256,
        "hasFile": bool(item.file_sha256 and item.file_size),
        "previewPath": (
            f"/api/materials/{entity_id(item)}/content"
            if item.file_sha256 and item.file_size
            else None
        ),
        "enabled": item.enabled,
        "createdAt": iso(item.created_at),
        "updatedAt": iso(item.updated_at),
    }


@router.get("")
@legacy_router.get("")
def list_materials(
    db: DbSession,
    current_user: CurrentUser,
    material_type: str | None = Query(default=None, alias="type"),
    text_role: str | None = Query(default=None, alias="textRole"),
) -> dict:
    statement = select(Material)
    if material_type:
        statement = statement.where(Material.material_type == material_type.strip().lower())
    if text_role:
        try:
            normalized_role = normalize_text_role(text_role)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        statement = statement.where(
            Material.material_type == "text", Material.text_role == normalized_role
        )
    if current_user.role != "admin":
        statement = statement.where(Material.created_by == current_user.id)
    items = db.scalars(statement.order_by(Material.created_at.desc())).all()
    rows = [material_row(item) for item in items]
    return {"data": {"rows": rows, "total": len(rows)}}


@router.get("/capabilities")
def material_capabilities() -> dict:
    return {
        "data": {
            "textRoles": [
                {
                    "value": role,
                    "label": TEXT_ROLE_LABELS[role],
                    "maxLength": TEXT_ROLE_LIMITS[role],
                    "multiline": role == "body",
                }
                for role in TEXT_MATERIAL_ROLES
            ]
        }
    }


@router.post("", status_code=201)
@legacy_router.post("", status_code=201)
def create_material(
    payload: MaterialCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    item = Material(
        public_id=new_public_id("mat"),
        name=payload.name,
        material_type=payload.material_type,
        text_role=payload.text_role if payload.material_type == "text" else None,
        content_json=payload.content_json,
        enabled=payload.enabled,
        created_by=current_user.id,
    )
    db.add(item)
    db.commit()
    return {"data": {"material": material_row(item)}}


@router.post("/upload", status_code=201)
@legacy_router.post("/upload", status_code=201)
async def upload_material(
    db: DbSession,
    current_user: CurrentUser,
    name: str = Form(..., min_length=1, max_length=120),
    type: str = Form(...),
    enabled: bool = Form(default=True),
    file: UploadFile = File(...),
) -> dict:
    material_type = type.strip().lower()
    if material_type not in BINARY_MATERIAL_TYPES:
        raise HTTPException(status_code=422, detail="该素材类型不支持文件上传")
    content, file_name, content_type, sha256 = await read_material_upload(
        material_type, file
    )
    item = Material(
        public_id=new_public_id("mat"),
        name=name.strip(),
        material_type=material_type,
        text_role=None,
        content_json={},
        file_name=file_name,
        content_type=content_type,
        file_size=len(content),
        file_sha256=sha256,
        content=content,
        enabled=enabled,
        created_by=current_user.id,
    )
    db.add(item)
    db.commit()
    return {"data": {"material": material_row(item)}}


@router.get("/{material_id}")
@legacy_router.get("/{material_id}")
def get_material(
    material_id: str,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    return {"data": {"material": material_row(_one(db, material_id, current_user))}}


def _content_response(item: Material, *, download: bool) -> Response:
    if not item.content or not item.content_type or not item.file_sha256:
        raise HTTPException(status_code=409, detail="素材文件尚未上传")
    filename = safe_filename(item.file_name)
    disposition = "attachment" if download else "inline"
    return Response(
        content=item.content,
        media_type=item.content_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(filename)}",
            "ETag": f'"{item.file_sha256}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{material_id}/content")
def get_material_content(
    material_id: str,
    db: DbSession,
    current_user: CurrentUser,
    download: bool = False,
) -> Response:
    return _content_response(
        _one(db, material_id, current_user), download=download
    )


@internal_router.get("/{material_id}/content")
def get_internal_material_content(
    material_id: str,
    db: DbSession,
    authorization: str | None = Header(default=None),
) -> Response:
    try:
        numeric_id = int(material_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="素材不存在") from exc
    item = db.get(Material, numeric_id)
    if item is None or not item.enabled:
        raise HTTPException(status_code=404, detail="素材不存在")
    token = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
    if not item.file_sha256 or not verify_material_access_token(
        token, item.id, item.file_sha256
    ):
        raise HTTPException(status_code=401, detail="素材访问凭证无效")
    return _content_response(item, download=False)


@router.put("/{material_id}/content")
async def replace_material_content(
    material_id: str,
    db: DbSession,
    current_user: CurrentUser,
    file: UploadFile = File(...),
) -> dict:
    item = _one(db, material_id, current_user)
    if item.material_type not in BINARY_MATERIAL_TYPES:
        raise HTTPException(status_code=422, detail="该素材类型没有可替换的文件")
    content, file_name, content_type, sha256 = await read_material_upload(
        item.material_type, file
    )
    item.file_name = file_name
    item.content_type = content_type
    item.file_size = len(content)
    item.file_sha256 = sha256
    item.content = content
    db.commit()
    return {"data": {"material": material_row(item)}}


@router.patch("/{material_id}")
@legacy_router.patch("/{material_id}")
def update_material(
    material_id: str,
    payload: MaterialUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    item = _one(db, material_id, current_user)
    if (
        payload.material_type is not None
        and payload.material_type != item.material_type
    ):
        raise HTTPException(status_code=422, detail="素材类型不能修改，请新建素材")
    if item.material_type in BINARY_MATERIAL_TYPES and payload.content_json is not None:
        raise HTTPException(status_code=422, detail="文件素材不能使用地址或文本覆盖")
    if item.material_type != "text" and "text_role" in payload.model_fields_set:
        raise HTTPException(status_code=422, detail="只有文本素材可以设置用途")
    if item.material_type == "text" and (
        "text_role" in payload.model_fields_set
        or payload.content_json is not None
    ):
        role = payload.text_role or item.text_role or "body"
        content = payload.content_json if payload.content_json is not None else item.content_json
        try:
            item.content_json = validate_text_material_content(content, role)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        item.text_role = role
    for field, attribute in (
        ("name", "name"),
        ("enabled", "enabled"),
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(item, attribute, value)
    db.commit()
    return {"data": {"material": material_row(item)}}


@router.delete("/{material_id}")
@legacy_router.delete("/{material_id}")
def delete_material(
    material_id: str,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    item = _one(db, material_id, current_user)
    template_count = db.scalar(
        select(func.count())
        .select_from(HyperlinkTemplate)
        .where(
            HyperlinkTemplate.material_id == item.id,
        )
    )
    if template_count:
        raise HTTPException(status_code=409, detail="素材仍被模板使用")
    db.delete(item)
    db.commit()
    return {"data": {"ok": True}}
