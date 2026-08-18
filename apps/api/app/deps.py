from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import (
    AuthSession,
    RoleActionPermission,
    RoleMenuPermission,
    SystemMenu,
    UserAccount,
)
from app.security import secret_fingerprint, utcnow


DbSession = Annotated[Session, Depends(get_db)]


def _request_token(request: Request) -> str | None:
    authorization = request.headers.get("Authorization", "")
    scheme, _, bearer = authorization.partition(" ")
    if scheme.lower() == "bearer" and bearer.strip():
        return bearer.strip()
    return request.cookies.get(get_settings().auth_cookie_name)


def _validate_cookie_request_origin(request: Request) -> None:
    """Reject cross-origin browser writes that authenticate with a cookie.

    Bearer clients do not rely on ambient browser credentials and therefore do
    not need this check. Requests without an Origin header are retained for
    non-browser clients and internal health/admin tooling.
    """

    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    authorization = request.headers.get("Authorization", "")
    scheme, _, bearer = authorization.partition(" ")
    if scheme.lower() == "bearer" and bearer.strip():
        return
    origin = request.headers.get("Origin")
    if not origin:
        return
    allowed_origins = {item.rstrip("/") for item in get_settings().cors_origins}
    if origin.rstrip("/") not in allowed_origins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="跨站请求已拒绝",
        )


def _request_permission(method: str, path: str) -> tuple[str | None, bool] | None:
    # These endpoints intentionally require only a valid session. Every other
    # CurrentUser endpoint must be mapped below or non-admin users fail closed.
    if path in {
        "/api/auth/me",
        "/api/auth/logout",
        "/api/system/metrics",
        "/api/system/menus/me",
    }:
        return None, False
    if path.startswith(
        (
            "/api/users",
            "/api/user-groups",
            "/api/system/roles",
            "/api/system/menus",
            "/api/system/configuration",
        )
    ):
        # These routes have their own AdminUser dependency. Marking them as
        # authenticated-only here lets that dependency provide the final
        # administrator check and its specific error response.
        return None, False
    if path.startswith("/api/developer-docs"):
        return "system.developer_docs.read", False
    if path == "/api/personal-accounts/intake/attempts":
        return "resources.account_intake.read", False
    if path == "/api/personal-accounts/import":
        return "resources.accounts.import", True
    if path == "/api/personal-accounts/export/batch":
        return "resources.accounts.export", True
    if path.startswith("/api/personal-accounts/") and path.endswith("/export"):
        return "resources.accounts.export", True
    rules = (
        ("/api/account-statistics", "resources.account_statistics.read", None),
        ("/api/protocol-pools", "resources.protocol.read", "resources.protocol.manage"),
        ("/api/bitly-accounts", "marketing.direct_short_links.read", "marketing.direct_short_links.manage"),
        ("/api/direct-short-links/accounts", "marketing.direct_short_links.read", "marketing.direct_short_links.manage"),
        ("/api/promotion/template-kits", "promotion.templates.read", None),
        ("/api/promotion/data-center/trends", "promotion.trends.read", None),
        ("/api/promotion/data-center", "promotion.statistics.read", None),
        ("/api/promotion/ad-metrics", "promotion.statistics.read", "promotion.statistics.manage"),
        ("/api/promotion/integrations", "promotion.integrations.read", "promotion.integrations.manage"),
        ("/api/promotion/template-policy", "promotion.templates.read", "promotion.templates.manage"),
        ("/api/promotion/templates", "promotion.templates.read", "promotion.templates.manage"),
        ("/api/promotion/channels", "promotion.channels.read", "promotion.channels.manage"),
        ("/api/domain-orders", "promotion.domain.read", "promotion.domain.purchase"),
        ("/api/domains", "promotion.domain.read", "promotion.domain.manage"),
        ("/api/meta-pixels", "promotion.channels.read", "promotion.channels.manage"),
        ("/api/personal-accounts", "resources.accounts.read", "resources.accounts.manage"),
        ("/api/account-groups", "resources.account_groups.read", "resources.accounts.manage"),
        ("/api/protocol-nodes", "resources.protocol.read", "resources.protocol.manage"),
        ("/api/materials", "resources.materials.read", "resources.materials.manage"),
        ("/api/hyperlink/tasks", "marketing.hyperlink_tasks.read", "marketing.hyperlink_tasks.manage"),
        ("/api/hyperlink/data-packages", "marketing.data_packages.read", "marketing.data_packages.manage"),
        ("/api/hyperlink/templates", "marketing.hyperlink_templates.read", "marketing.hyperlink_templates.manage"),
        ("/api/hyperlink/strategies", "marketing.hyperlink_strategies.read", "marketing.hyperlink_strategies.manage"),
        ("/api/hyperlink/materials", "resources.materials.read", "resources.materials.manage"),
        ("/api/hyperlink/market-insights", "marketing.insights.read", None),
        ("/api/direct-short-links", "marketing.direct_short_links.read", "marketing.direct_short_links.manage"),
    )
    if path.startswith(
        ("/api/ip-allocation-policy", "/api/ip-proxies", "/api/ip-proxy-bindings")
    ):
        if method == "GET":
            return None, False
        return "resources.ip.manage", True
    for prefix, read_permission, write_permission in rules:
        if path.startswith(prefix):
            if method == "GET":
                return read_permission, False
            return (write_permission, True) if write_permission else None
    return None


def get_current_user(request: Request, db: DbSession) -> UserAccount:
    token = _request_token(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    _validate_cookie_request_origin(request)
    auth_session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == secret_fingerprint(token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > utcnow(),
        )
    )
    if auth_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期")
    user = db.get(UserAccount, auth_session.user_id)
    if user is None or not user.is_active or not user.group.enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已停用")
    required_permission = _request_permission(request.method, request.url.path)
    if user.role != "admin":
        if required_permission is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="该接口未配置访问权限",
            )
        permission_key, is_action = required_permission
        if permission_key is None:
            request.state.auth_session = auth_session
            return user
        if is_action:
            allowed = db.scalar(
                select(RoleActionPermission.id).where(
                    RoleActionPermission.role_id == user.group_id,
                    RoleActionPermission.permission_key == permission_key,
                )
            )
        else:
            allowed = db.scalar(
                select(RoleMenuPermission.id)
                .join(SystemMenu)
                .where(
                    RoleMenuPermission.role_id == user.group_id,
                    SystemMenu.permission_key == permission_key,
                    SystemMenu.enabled.is_(True),
                )
            )
        if allowed is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="没有此功能权限")
    request.state.auth_session = auth_session
    return user


def get_optional_current_user(request: Request, db: Session) -> UserAccount | None:
    """Resolve an authenticated control-plane user without making auth mandatory.

    Public promotion routes use this only to distinguish an authorized backend
    preview from an anonymous visitor. Invalid, expired or disabled sessions are
    deliberately treated as anonymous.
    """

    token = _request_token(request)
    if not token:
        return None
    auth_session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == secret_fingerprint(token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > utcnow(),
        )
    )
    if auth_session is None:
        return None
    user = db.get(UserAccount, auth_session.user_id)
    if user is None or not user.is_active or not user.group.enabled:
        return None
    return user


CurrentUser = Annotated[UserAccount, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> UserAccount:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


AdminUser = Annotated[UserAccount, Depends(require_admin)]
