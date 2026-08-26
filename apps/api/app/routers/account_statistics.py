from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.deps import CurrentUser, DbSession
from app.services import account_statistics


router = APIRouter(prefix="/api/account-statistics", tags=["account-statistics"])


@router.get("/overview")
def overview(db: DbSession, current_user: CurrentUser) -> dict:
    return {"data": account_statistics.overview(db, current_user)}


@router.get("/countries")
def countries(db: DbSession, current_user: CurrentUser) -> dict:
    rows = account_statistics.countries(db, current_user)
    return {"data": {"rows": rows, "total": len(rows)}}


@router.get("/daily")
def daily(
    db: DbSession,
    current_user: CurrentUser,
    date_from: date = Query(alias="dateFrom"),
    date_to: date = Query(alias="dateTo"),
    country_code: str | None = Query(
        default=None,
        alias="countryCode",
        min_length=2,
        max_length=2,
        pattern=r"^[A-Za-z]{2}$",
    ),
    sort_by: Literal["date"] = Query(default="date", alias="sortBy"),
    sort_order: Literal["asc", "desc"] = Query(default="asc", alias="sortOrder"),
) -> dict:
    if date_from > date_to:
        raise HTTPException(status_code=422, detail="开始日期不能晚于结束日期")
    if (date_to - date_from).days > 89:
        raise HTTPException(status_code=422, detail="日期范围不能超过 90 天")
    normalized_country = country_code.upper() if country_code else None
    rows, collection_started_at = account_statistics.daily(
        db,
        current_user,
        date_from=date_from,
        date_to=date_to,
        country_code=normalized_country,
    )
    if sort_order == "desc":
        rows = list(reversed(rows))
    return {
        "data": {
            "rows": rows,
            "total": len(rows),
            "collectionStartedAt": collection_started_at.isoformat(),
            "timezone": "Asia/Shanghai",
            "definitions": {
                "validAccounts": "日末状态为可连接或在线的账号",
                "onlineRate": "在线账号数 / 有效账号数",
                "retainedAccounts": "日初仍未失效的存量账号",
                "newInvalidRate": "当日新增后又当日失效的账号数 / 当日新增数",
                "invalidatedAccounts": "当日首次进入 restricted，或收到 confirmed logged_out 的账号数",
                "preMarketingInvalid": "失效前没有成功 sent/delivered 记录",
                "postMarketingInvalid": "失效前至少有一条成功 sent/delivered 记录",
                "overallInvalidRate": "当日失效账号数 /（日初留存 + 当日新增）",
            },
        }
    }
