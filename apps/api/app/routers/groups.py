from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.deps import AdminUser, DbSession
from app.models import RoleActionPermission, RoleMenuPermission, UserAccount, UserGroup
from app.schemas import GroupCreate, GroupUpdate
from app.serializers import group_row


router = APIRouter(prefix="/api/user-groups", tags=["user-groups"])


@router.get("")
def list_groups(db: DbSession, _admin: AdminUser) -> dict:
    counts = dict(
        db.execute(
            select(UserAccount.group_id, func.count(UserAccount.id)).group_by(UserAccount.group_id)
        ).all()
    )
    groups = db.scalars(select(UserGroup).order_by(UserGroup.is_builtin.desc(), UserGroup.id)).all()
    rows = [group_row(group, int(counts.get(group.id, 0))) for group in groups]
    return {"data": {"rows": rows, "total": len(rows)}}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_group(payload: GroupCreate, db: DbSession, _admin: AdminUser) -> dict:
    group = UserGroup(name=payload.name, description=payload.description, is_builtin=False)
    db.add(group)
    try:
        db.flush()
        operator = db.scalar(select(UserGroup).where(UserGroup.system_key == "operator"))
        if operator:
            for permission in operator.menu_permissions:
                group.menu_permissions.append(RoleMenuPermission(menu_id=permission.menu_id))
            for permission in operator.action_permissions:
                group.action_permissions.append(
                    RoleActionPermission(permission_key=permission.permission_key)
                )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="用户组名称已存在") from None
    db.refresh(group)
    return {"data": {"group": group_row(group)}}


@router.patch("/{group_id}")
def update_group(
    group_id: int, payload: GroupUpdate, db: DbSession, _admin: AdminUser
) -> dict:
    group = db.get(UserGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="用户组不存在")
    if payload.name is not None:
        if group.is_builtin:
            raise HTTPException(status_code=400, detail="内置用户组不能改名")
        group.name = payload.name
    if "description" in payload.model_fields_set:
        group.description = payload.description
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="用户组名称已存在") from None
    db.refresh(group)
    count = db.scalar(select(func.count()).select_from(UserAccount).where(UserAccount.group_id == group.id))
    return {"data": {"group": group_row(group, int(count or 0))}}


@router.delete("/{group_id}")
def delete_group(group_id: int, db: DbSession, _admin: AdminUser) -> dict:
    group = db.get(UserGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="用户组不存在")
    if group.is_builtin:
        raise HTTPException(status_code=400, detail="内置用户组不能删除")
    user_count = db.scalar(
        select(func.count()).select_from(UserAccount).where(UserAccount.group_id == group.id)
    )
    if user_count:
        raise HTTPException(status_code=409, detail="用户组下仍有用户，不能删除")
    db.delete(group)
    db.commit()
    return {"data": {"ok": True}}
