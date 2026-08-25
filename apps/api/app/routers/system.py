from __future__ import annotations

from typing import Literal


from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.deps import AdminUser, CurrentUser, DbSession
from app.entity_ids import (
    entity_id,
    identifier_filter,
    identifiers_filter,
    matches_identifier,
)
from app.models import (
    AuthSession,
    RoleActionPermission,
    RoleMenuPermission,
    SystemMenu,
    UserAccount,
    UserGroup,
)
from app.security import utcnow
from app.schemas import RoleCreate, RoleUpdate
from app.serializers import iso
from app.services.system_metrics import system_resource_metrics


router = APIRouter(prefix="/api/system", tags=["system-management"])
ACTION_PERMISSION_KEYS = {
    "business.personal_accounts.manage",
    "resources.accounts.manage",
    "resources.accounts.import",
    "resources.accounts.export",
    "resources.protocol.manage",
    "promotion.templates.manage",
    "promotion.channels.manage",
    "promotion.domain.manage",
    "promotion.domain.purchase",
    "promotion.statistics.manage",
    "marketing.hyperlink_tasks.manage",
    "marketing.data_packages.manage",
    "marketing.hyperlink_templates.manage",
    "marketing.hyperlink_strategies.manage",
    "resources.materials.manage",
    "marketing.direct_short_links.manage",
    "resources.ip.manage",
}


@router.get("/metrics")
def get_system_metrics(_current_user: CurrentUser) -> dict:
    return {"data": system_resource_metrics()}


def _menu_row(item: SystemMenu) -> dict:
    return {
        "id": entity_id(item),
        "parentId": entity_id(item.parent) if item.parent else None,
        "name": item.name,
        "type": item.menu_type,
        "routePath": item.route_path,
        "icon": item.icon,
        "permissionKey": item.permission_key,
        "sortOrder": item.sort_order,
        "enabled": item.enabled,
        "visible": item.visible,
        "isBuiltin": item.is_builtin,
        "createdAt": iso(item.created_at),
        "updatedAt": iso(item.updated_at),
    }


def _menu_tree(items: list[SystemMenu]) -> list[dict]:
    rows = {item.id: {**_menu_row(item), "children": []} for item in items}
    roots: list[dict] = []
    for item in sorted(items, key=lambda value: (value.sort_order, value.id)):
        row = rows[item.id]
        if item.parent_id in rows:
            rows[item.parent_id]["children"].append(row)
        else:
            roots.append(row)
    return roots


def _role(db: DbSession, role_id: str) -> UserGroup:
    item = db.scalar(select(UserGroup).where(identifier_filter(UserGroup, role_id)))
    if item is None:
        raise HTTPException(status_code=404, detail="角色不存在")
    return item


def _role_row(
    db: DbSession,
    item: UserGroup,
    user_count: int | None = None,
) -> dict:
    if user_count is None:
        user_count = int(
            db.scalar(
                select(func.count())
                .select_from(UserAccount)
                .where(UserAccount.group_id == item.id)
            )
            or 0
        )
    menu_ids = [
        entity_id(permission.menu)
        for permission in sorted(
            item.menu_permissions, key=lambda permission: permission.menu.sort_order
        )
    ]
    return {
        "id": str(item.id),
        "name": item.name,
        "systemKey": item.system_key,
        "description": item.description,
        "isBuiltin": item.is_builtin,
        "enabled": item.enabled,
        "userCount": user_count,
        "menuIds": menu_ids,
        "permissionKeys": sorted(
            permission.permission_key for permission in item.action_permissions
        ),
        "createdAt": iso(item.created_at),
        "updatedAt": iso(item.updated_at),
    }


def _permission_menus(db: DbSession, menu_ids: list[str]) -> list[SystemMenu]:
    unique_ids = list(dict.fromkeys(menu_ids))
    if not unique_ids:
        return []
    menus = db.scalars(
        select(SystemMenu).where(identifiers_filter(SystemMenu, unique_ids))
    ).all()
    if any(
        not any(matches_identifier(menu, requested) for menu in menus)
        for requested in unique_ids
    ):
        raise HTTPException(status_code=422, detail="菜单权限包含不存在的菜单")
    expanded = {menu.id: menu for menu in menus}
    for menu in list(menus):
        parent = menu.parent
        while parent is not None:
            expanded[parent.id] = parent
            parent = parent.parent
    return list(expanded.values())


def _replace_permissions(db: DbSession, role: UserGroup, menu_ids: list[str]) -> None:
    if role.system_key == "admin":
        menus = db.scalars(select(SystemMenu)).all()
    else:
        menus = _permission_menus(db, menu_ids)
    role.menu_permissions.clear()
    db.flush()
    for menu in menus:
        role.menu_permissions.append(RoleMenuPermission(menu_id=menu.id))


def _replace_action_permissions(
    db: DbSession, role: UserGroup, permission_keys: list[str]
) -> None:
    requested = set(permission_keys)
    unknown = requested - ACTION_PERMISSION_KEYS
    if unknown:
        raise HTTPException(status_code=422, detail="操作权限包含未知标识")
    if role.system_key == "admin":
        requested = ACTION_PERMISSION_KEYS
    role.action_permissions.clear()
    db.flush()
    for permission_key in sorted(requested):
        role.action_permissions.append(
            RoleActionPermission(permission_key=permission_key)
        )


@router.get("/roles")
def list_roles(
    db: DbSession,
    _admin: AdminUser,
    keyword: str | None = None,
    is_builtin: bool | None = Query(default=None, alias="isBuiltin"),
    enabled: bool | None = None,
    sort_by: Literal[
        "id",
        "isBuiltin",
        "userCount",
        "createdAt",
        "updatedAt",
    ] = Query(default="id", alias="sortBy"),
    sort_order: Literal["asc", "desc"] = Query(default="asc", alias="sortOrder"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
) -> dict:
    conditions = []
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        conditions.append(
            or_(
                UserGroup.name.ilike(pattern),
                UserGroup.description.ilike(pattern),
            )
        )
    if is_builtin is not None:
        conditions.append(UserGroup.is_builtin.is_(is_builtin))
    if enabled is not None:
        conditions.append(UserGroup.enabled.is_(enabled))

    count_statement = select(UserGroup.id).where(*conditions)
    total = int(
        db.scalar(select(func.count()).select_from(count_statement.subquery())) or 0
    )
    user_count = func.count(UserAccount.id).label("user_count")
    statement = (
        select(UserGroup, user_count)
        .outerjoin(UserAccount, UserAccount.group_id == UserGroup.id)
        .where(*conditions)
        .group_by(UserGroup.id)
    )
    sort_columns = {
        "id": UserGroup.id,
        "isBuiltin": UserGroup.is_builtin,
        "userCount": user_count,
        "createdAt": UserGroup.created_at,
        "updatedAt": UserGroup.updated_at,
    }
    sort_column = sort_columns[sort_by]
    order_by = (
        sort_column.asc().nullslast()
        if sort_order == "asc"
        else sort_column.desc().nullslast()
    )
    ordering = [order_by]
    if sort_by != "id":
        ordering.append(
            UserGroup.id.asc() if sort_order == "asc" else UserGroup.id.desc()
        )
    roles = db.execute(
        statement.order_by(*ordering)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "data": {
            "rows": [
                _role_row(db, role, int(role_user_count))
                for role, role_user_count in roles
            ],
            "total": total,
            "page": page,
            "pageSize": page_size,
        }
    }


@router.get("/roles/options")
def list_role_options(db: DbSession, _admin: AdminUser) -> dict:
    roles = db.scalars(
        select(UserGroup)
        .order_by(UserGroup.is_builtin.desc(), UserGroup.id)
    ).all()
    return {
        "data": {
            "rows": [
                {
                    "id": entity_id(role),
                    "name": role.name,
                    "systemKey": role.system_key,
                }
                for role in roles
            ],
            "total": len(roles),
        }
    }


@router.post("/roles", status_code=status.HTTP_201_CREATED)
def create_role(payload: RoleCreate, db: DbSession, _admin: AdminUser) -> dict:
    role = UserGroup(
        name=payload.name,
        description=payload.description,
        is_builtin=False,
        enabled=payload.enabled,
    )
    db.add(role)
    try:
        db.flush()
        _replace_permissions(db, role, payload.menu_ids)
        _replace_action_permissions(db, role, payload.permission_keys)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="角色名称已存在") from None
    db.refresh(role)
    return {"data": {"role": _role_row(db, role)}}


@router.patch("/roles/{role_id}")
def update_role(
    role_id: str, payload: RoleUpdate, db: DbSession, _admin: AdminUser
) -> dict:
    role = _role(db, role_id)
    if role.is_builtin and (payload.name is not None or payload.enabled is False):
        raise HTTPException(status_code=400, detail="内置角色不能改名或停用")
    if payload.name is not None:
        role.name = payload.name
    if "description" in payload.model_fields_set:
        role.description = payload.description
    if payload.enabled is not None:
        role.enabled = payload.enabled
    if payload.menu_ids is not None:
        _replace_permissions(db, role, payload.menu_ids)
    if payload.permission_keys is not None:
        _replace_action_permissions(db, role, payload.permission_keys)
    security_changed = bool(
        payload.enabled is not None
        or payload.menu_ids is not None
        or payload.permission_keys is not None
    )
    if security_changed:
        user_ids = select(UserAccount.id).where(UserAccount.group_id == role.id)
        db.execute(
            update(AuthSession)
            .where(
                AuthSession.user_id.in_(user_ids),
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=utcnow())
        )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="角色名称已存在") from None
    db.refresh(role)
    return {"data": {"role": _role_row(db, role)}}


@router.delete("/roles/{role_id}")
def delete_role(role_id: str, db: DbSession, _admin: AdminUser) -> dict:
    role = _role(db, role_id)
    if role.is_builtin:
        raise HTTPException(status_code=400, detail="内置角色不能删除")
    user_count = db.scalar(
        select(func.count()).select_from(UserAccount).where(UserAccount.group_id == role.id)
    )
    if user_count:
        raise HTTPException(status_code=409, detail="角色仍有关联用户")
    db.delete(role)
    db.commit()
    return {"data": {"ok": True}}


@router.get("/menus")
def list_menus(db: DbSession, _admin: AdminUser) -> dict:
    menus = db.scalars(select(SystemMenu).order_by(SystemMenu.sort_order, SystemMenu.id)).all()
    return {
        "data": {
            "rows": [_menu_row(menu) for menu in menus],
            "tree": _menu_tree(list(menus)),
            "total": len(menus),
        }
    }


@router.get("/menus/me")
def my_menus(db: DbSession, current_user: CurrentUser) -> dict:
    statement = select(SystemMenu).where(SystemMenu.enabled.is_(True))
    if current_user.role != "admin":
        statement = statement.join(RoleMenuPermission).where(
            RoleMenuPermission.role_id == current_user.group_id
        )
    menus = db.scalars(statement.order_by(SystemMenu.sort_order, SystemMenu.id)).all()
    allowed_ids = {menu.id for menu in menus}
    visible = []
    for menu in menus:
        if not menu.visible:
            continue
        ancestor = menu.parent
        include = True
        while ancestor is not None:
            if ancestor.id not in allowed_ids or not ancestor.enabled or not ancestor.visible:
                include = False
                break
            ancestor = ancestor.parent
        if include:
            visible.append(menu)
    actions = sorted(
        ACTION_PERMISSION_KEYS
        if current_user.role == "admin"
        else {
            permission.permission_key
            for permission in current_user.group.action_permissions
        }
    )
    return {"data": {"tree": _menu_tree(visible), "permissions": sorted(
        menu.permission_key for menu in menus if menu.permission_key
    ), "actionPermissions": actions}}
