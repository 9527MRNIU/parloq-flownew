from __future__ import annotations


from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.deps import AdminUser, CurrentUser, DbSession
from app.snowflake import new_public_id

from app.models import (
    RoleActionPermission,
    RoleMenuPermission,
    SystemMenu,
    UserAccount,
    UserGroup,
)
from app.schemas import MenuCreate, MenuUpdate, RoleCreate, RoleUpdate
from app.serializers import iso


router = APIRouter(prefix="/api/system", tags=["system-management"])
ACTION_PERMISSION_KEYS = {
    "business.personal_accounts.manage",
    "resources.accounts.manage",
    "resources.accounts.import",
    "resources.accounts.export",
    "promotion.templates.manage",
    "promotion.channels.manage",
    "promotion.domain.manage",
    "promotion.domain.purchase",
    "promotion.statistics.manage",
    "marketing.hyperlink_tasks.manage",
    "marketing.data_packages.manage",
    "marketing.hyperlink_templates.manage",
    "marketing.hyperlink_strategies.manage",
    "marketing.materials.manage",
    "marketing.direct_short_links.manage",
    "resources.ip.manage",
}


def _menu_row(item: SystemMenu) -> dict:
    return {
        "id": item.public_id,
        "publicId": item.public_id,
        "parentId": item.parent.public_id if item.parent else None,
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


def _menu(db: DbSession, public_id: str) -> SystemMenu:
    item = db.scalar(select(SystemMenu).where(SystemMenu.public_id == public_id))
    if item is None:
        raise HTTPException(status_code=404, detail="菜单不存在")
    return item


def _role(db: DbSession, role_id: int) -> UserGroup:
    item = db.get(UserGroup, role_id)
    if item is None:
        raise HTTPException(status_code=404, detail="角色不存在")
    return item


def _role_row(db: DbSession, item: UserGroup) -> dict:
    user_count = int(
        db.scalar(
            select(func.count()).select_from(UserAccount).where(UserAccount.group_id == item.id)
        )
        or 0
    )
    menu_ids = [
        permission.menu.public_id
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
    menus = db.scalars(select(SystemMenu).where(SystemMenu.public_id.in_(unique_ids))).all()
    if len(menus) != len(unique_ids):
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
def list_roles(db: DbSession, _admin: AdminUser) -> dict:
    roles = db.scalars(
        select(UserGroup).order_by(UserGroup.is_builtin.desc(), UserGroup.id)
    ).all()
    return {"data": {"rows": [_role_row(db, role) for role in roles], "total": len(roles)}}


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
    role_id: int, payload: RoleUpdate, db: DbSession, _admin: AdminUser
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
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="角色名称已存在") from None
    db.refresh(role)
    return {"data": {"role": _role_row(db, role)}}


@router.delete("/roles/{role_id}")
def delete_role(role_id: int, db: DbSession, _admin: AdminUser) -> dict:
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


def _validate_menu_shape(menu_type: str, route_path: str | None, permission_key: str | None) -> None:
    if menu_type == "page" and (not route_path or not route_path.startswith("/")):
        raise HTTPException(status_code=422, detail="页面菜单必须提供以 / 开头的路由")
    if route_path and not route_path.startswith("/"):
        raise HTTPException(status_code=422, detail="菜单路由必须以 / 开头")
    if permission_key and any(character.isspace() for character in permission_key):
        raise HTTPException(status_code=422, detail="权限标识不能包含空格")


@router.post("/menus", status_code=status.HTTP_201_CREATED)
def create_menu(payload: MenuCreate, db: DbSession, _admin: AdminUser) -> dict:
    _validate_menu_shape(payload.menu_type, payload.route_path, payload.permission_key)
    parent = _menu(db, payload.parent_id) if payload.parent_id else None
    if parent is not None and parent.menu_type != "directory":
        raise HTTPException(status_code=422, detail="父菜单必须是目录")
    item = SystemMenu(
        public_id=new_public_id("menu"),
        parent_id=parent.id if parent else None,
        name=payload.name,
        menu_type=payload.menu_type,
        route_path=payload.route_path,
        icon=payload.icon,
        permission_key=payload.permission_key,
        sort_order=payload.sort_order,
        enabled=payload.enabled,
        visible=payload.visible,
        is_builtin=False,
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="菜单路由或权限标识已存在") from None
    db.refresh(item)
    return {"data": {"menu": _menu_row(item)}}


@router.patch("/menus/{public_id}")
def update_menu(
    public_id: str, payload: MenuUpdate, db: DbSession, _admin: AdminUser
) -> dict:
    item = _menu(db, public_id)
    if item.is_builtin and {
        "parent_id",
        "route_path",
        "permission_key",
    }.intersection(payload.model_fields_set):
        raise HTTPException(
            status_code=400, detail="内置菜单只能修改名称、图标、顺序和显示状态"
        )
    parent = item.parent
    if "parent_id" in payload.model_fields_set:
        parent = _menu(db, payload.parent_id) if payload.parent_id else None
        if parent and (parent.id == item.id or parent.menu_type != "directory"):
            raise HTTPException(status_code=422, detail="父菜单无效")
        ancestor = parent
        while ancestor is not None:
            if ancestor.id == item.id:
                raise HTTPException(status_code=422, detail="菜单层级不能形成循环")
            ancestor = ancestor.parent
    route_path = payload.route_path if "route_path" in payload.model_fields_set else item.route_path
    permission_key = (
        payload.permission_key
        if "permission_key" in payload.model_fields_set
        else item.permission_key
    )
    _validate_menu_shape(item.menu_type, route_path, permission_key)
    if payload.name is not None:
        item.name = payload.name
    if "parent_id" in payload.model_fields_set:
        item.parent_id = parent.id if parent else None
    if "route_path" in payload.model_fields_set:
        item.route_path = payload.route_path
    if "icon" in payload.model_fields_set:
        item.icon = payload.icon
    if "permission_key" in payload.model_fields_set:
        item.permission_key = payload.permission_key
    if payload.sort_order is not None:
        item.sort_order = payload.sort_order
    if payload.enabled is not None:
        item.enabled = payload.enabled
    if payload.visible is not None:
        item.visible = payload.visible
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="菜单路由或权限标识已存在") from None
    db.refresh(item)
    return {"data": {"menu": _menu_row(item)}}


@router.delete("/menus/{public_id}")
def delete_menu(public_id: str, db: DbSession, _admin: AdminUser) -> dict:
    item = _menu(db, public_id)
    if item.is_builtin:
        raise HTTPException(status_code=400, detail="内置菜单不能删除")
    child_count = db.scalar(
        select(func.count()).select_from(SystemMenu).where(SystemMenu.parent_id == item.id)
    )
    if child_count:
        raise HTTPException(status_code=409, detail="请先删除子菜单")
    db.delete(item)
    db.commit()
    return {"data": {"ok": True}}
