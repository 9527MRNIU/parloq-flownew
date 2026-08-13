from __future__ import annotations

from sqlalchemy.sql import Select

from app.models import UserAccount


def owner_filter(statement: Select, model: type, user: UserAccount) -> Select:
    if user.role != "admin":
        statement = statement.where(model.created_by == user.id)
    return statement


def owns(item: object, user: UserAccount) -> bool:
    return user.role == "admin" or getattr(item, "created_by", None) == user.id
