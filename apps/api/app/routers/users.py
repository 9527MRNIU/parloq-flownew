from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.deps import AdminUser, DbSession
from app.models import AuthSession, UserAccount, UserGroup, UserMfaCredential
from app.schemas import UserCreate, UserUpdate
from app.security import hash_password, utcnow
from app.serializers import user_row
from app.services.mfa import record_event
from app.snowflake import parse_snowflake_id


router = APIRouter(prefix="/api/users", tags=["users"])


def _group_or_404(db: DbSession, group_id: str) -> UserGroup:
    try:
        database_id = parse_snowflake_id(group_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="用户组不存在") from None
    group = db.get(UserGroup, database_id)
    if group is None or not group.enabled:
        raise HTTPException(status_code=404, detail="用户组不存在")
    return group


@router.get("")
def list_users(
    db: DbSession,
    _admin: AdminUser,
    keyword: str | None = None,
    group_id: str | None = Query(default=None, alias="groupId"),
    enabled: bool | None = None,
    is_admin: bool | None = Query(default=None, alias="isAdmin"),
    mfa_enabled: bool | None = Query(default=None, alias="mfaEnabled"),
    sort_by: Literal[
        "id",
        "groupName",
        "isAdmin",
        "mfaEnabled",
        "lastLoginAt",
        "createdAt",
        "updatedAt",
    ] = Query(default="id", alias="sortBy"),
    sort_order: Literal["asc", "desc"] = Query(default="desc", alias="sortOrder"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
) -> dict:
    is_admin_expression = UserAccount.role == "admin"
    mfa_enabled_expression = UserMfaCredential.enabled_at.is_not(None)
    statement = (
        select(UserAccount)
        .join(UserGroup)
        .outerjoin(UserMfaCredential, UserMfaCredential.user_id == UserAccount.id)
    )
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        statement = statement.where(
            or_(
                UserAccount.username.ilike(pattern),
                UserAccount.display_name.ilike(pattern),
                UserGroup.name.ilike(pattern),
            )
        )
    if group_id:
        try:
            database_group_id = parse_snowflake_id(group_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="角色筛选值无效") from None
        statement = statement.where(UserAccount.group_id == database_group_id)
    if enabled is not None:
        statement = statement.where(UserAccount.is_active.is_(enabled))
    if is_admin is not None:
        statement = statement.where(is_admin_expression.is_(is_admin))
    if mfa_enabled is not None:
        statement = statement.where(mfa_enabled_expression.is_(mfa_enabled))

    sort_columns = {
        "id": UserAccount.id,
        "groupName": UserGroup.name,
        "isAdmin": is_admin_expression,
        "mfaEnabled": mfa_enabled_expression,
        "lastLoginAt": UserAccount.last_login_at,
        "createdAt": UserAccount.created_at,
        "updatedAt": UserAccount.updated_at,
    }
    sort_column = sort_columns[sort_by]
    order_by = (
        sort_column.asc().nullslast()
        if sort_order == "asc"
        else sort_column.desc().nullslast()
    )
    tie_breaker = UserAccount.id.asc() if sort_order == "asc" else UserAccount.id.desc()
    total = int(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    ordering = [order_by]
    if sort_by != "id":
        ordering.append(tie_breaker)
    users = db.scalars(
        statement.order_by(*ordering)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "data": {
            "rows": [user_row(user) for user in users],
            "total": total,
            "page": page,
            "pageSize": page_size,
        }
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: DbSession, _admin: AdminUser) -> dict:
    group = _group_or_404(db, payload.group_id)
    user = UserAccount(
        username=payload.username,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        group_id=group.id,
        role="admin" if group.system_key == "admin" else "operator",
        is_active=payload.is_active,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="用户名已存在") from None
    db.refresh(user)
    return {"data": {"user": user_row(user, group)}}


@router.post("/{user_id}/mfa/reset")
def reset_user_mfa(
    user_id: str,
    request: Request,
    db: DbSession,
    current_admin: AdminUser,
) -> dict:
    try:
        database_id = parse_snowflake_id(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="用户不存在") from None
    user = db.get(UserAccount, database_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    credential = user.mfa_credential
    if credential is not None:
        db.delete(credential)
    db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow())
    )
    record_event(
        db,
        "admin_reset",
        user_id=user.id,
        actor_user_id=current_admin.id,
        source_ip=request.client.host if request.client else "unknown",
        details={"credentialExisted": credential is not None},
    )
    db.commit()
    return {"data": {"ok": True, "reset": credential is not None}}


@router.patch("/{user_id}")
def update_user(
    user_id: str,
    payload: UserUpdate,
    db: DbSession,
    current_admin: AdminUser,
) -> dict:
    try:
        database_id = parse_snowflake_id(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="用户不存在") from None
    user = db.get(UserAccount, database_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    group = user.group
    if payload.group_id is not None:
        group = _group_or_404(db, payload.group_id)
    next_role = "admin" if group.system_key == "admin" else "operator"
    next_active = payload.is_active if payload.is_active is not None else user.is_active
    if user.id == current_admin.id and (next_role != "admin" or not next_active):
        raise HTTPException(status_code=400, detail="不能停用自己或移除自己的管理员权限")
    if user.role == "admin" and (next_role != "admin" or not next_active):
        other_admins = db.scalar(
            select(func.count()).select_from(UserAccount).where(
                UserAccount.role == "admin",
                UserAccount.is_active.is_(True),
                UserAccount.id != user.id,
            )
        )
        if not other_admins:
            raise HTTPException(status_code=400, detail="不能停用最后一个管理员")
    security_changed = bool(
        payload.password
        or (payload.username is not None and payload.username != user.username)
        or group.id != user.group_id
        or next_role != user.role
        or next_active != user.is_active
    )
    if payload.username is not None:
        user.username = payload.username
    if "display_name" in payload.model_fields_set:
        user.display_name = payload.display_name
    if payload.password:
        user.password_hash = hash_password(payload.password)
    user.group_id = group.id
    user.role = next_role
    user.is_active = next_active
    if security_changed:
        db.execute(
            update(AuthSession)
            .where(
                AuthSession.user_id == user.id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=utcnow())
        )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="用户名已存在") from None
    db.refresh(user)
    return {"data": {"user": user_row(user, group)}}


@router.delete("/{user_id}")
def delete_user(user_id: str, db: DbSession, current_admin: AdminUser) -> dict:
    try:
        database_id = parse_snowflake_id(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="用户不存在") from None
    user = db.get(UserAccount, database_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == current_admin.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录用户")
    if user.role == "admin":
        other_admins = db.scalar(
            select(func.count()).select_from(UserAccount).where(
                UserAccount.role == "admin",
                UserAccount.is_active.is_(True),
                UserAccount.id != user.id,
            )
        )
        if not other_admins:
            raise HTTPException(status_code=400, detail="不能删除最后一个管理员")
    db.delete(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="用户仍有关联业务数据，请先删除或移交相关资源",
        ) from None
    return {"data": {"ok": True}}
