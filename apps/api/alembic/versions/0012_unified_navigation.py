"""Align the permission menu tree with unified accounts and group marketing."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0012_unified_navigation"
down_revision: str | None = "0011_ip_allocation_policies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NEW_MENUS = (
    ("menu_resources_accounts_import", "menu_resources_account_center", "账号导入", "page", "/resources/accounts/import", "resources.accounts.import", 311),
    ("menu_resources_accounts_export", "menu_resources_account_center", "账号导出", "page", "/resources/accounts/export", "resources.accounts.export", 312),
    ("menu_resources_accounts_groups", "menu_resources_account_center", "账号分组", "page", "/resources/accounts/groups", "resources.account_groups.read", 314),
    ("menu_resources_accounts_statistics", "menu_resources_account_center", "账号统计", "page", "/resources/accounts/statistics", "resources.account_statistics.read", 315),
    ("menu_resources_operations", "menu_resources", "运营管理", "directory", None, None, 320),
    ("menu_resources_protocol", "menu_resources_operations", "协议管理", "page", "/resources/operations/protocol", "resources.protocol.read", 321),
    ("menu_marketing_group", "menu_marketing", "拉群营销", "directory", None, None, 230),
    ("menu_marketing_group_blast_tasks", "menu_marketing_group", "拉群任务-炸群", "page", "/group-marketing/blast/tasks", "marketing.group_blast_tasks.read", 231),
    ("menu_marketing_group_blast_templates", "menu_marketing_group", "模板管理-炸群", "page", "/group-marketing/blast/templates", "marketing.group_blast_templates.read", 232),
    ("menu_marketing_group_script_tasks", "menu_marketing_group", "拉群任务-剧本", "page", "/group-marketing/script/tasks", "marketing.group_script_tasks.read", 233),
    ("menu_marketing_group_script_templates", "menu_marketing_group", "模板管理-剧本", "page", "/group-marketing/script/templates", "marketing.group_script_templates.read", 234),
    ("menu_marketing_group_verification", "menu_marketing_group", "收群验群任务", "page", "/group-marketing/verification-tasks", "marketing.group_verification_tasks.read", 235),
    ("menu_marketing_group_data_packages", "menu_marketing_group", "数据包", "page", "/group-marketing/data-packages", "marketing.group_data_packages.read", 236),
    ("menu_marketing_group_analysis", "menu_marketing_group", "拉群市场分析", "page", "/group-marketing/market-analysis", "marketing.group_market_analysis.read", 237),
)

NEW_ACTIONS = (
    "resources.accounts.manage",
    "resources.accounts.import",
    "resources.accounts.export",
)


def _menu_id(bind, menus, public_id: str) -> int:
    return int(
        bind.execute(
            sa.select(menus.c.id).where(menus.c.public_id == public_id)
        ).scalar_one()
    )


def upgrade() -> None:
    bind = op.get_bind()
    menus = sa.Table("system_menus", sa.MetaData(), autoload_with=bind)
    role_menus = sa.Table("role_menu_permissions", sa.MetaData(), autoload_with=bind)
    role_actions = sa.Table("role_action_permissions", sa.MetaData(), autoload_with=bind)
    roles = sa.Table("user_groups", sa.MetaData(), autoload_with=bind)

    resources_id = _menu_id(bind, menus, "menu_resources")
    account_center_id = _menu_id(bind, menus, "menu_business")
    account_manage_id = _menu_id(bind, menus, "menu_business_personal_accounts")
    bind.execute(
        menus.update().where(menus.c.id == account_center_id).values(
            public_id="menu_resources_account_center",
            parent_id=resources_id,
            name="账号中心",
            icon="BookUser",
            sort_order=310,
        )
    )
    bind.execute(
        menus.update().where(menus.c.id == account_manage_id).values(
            public_id="menu_resources_accounts_manage",
            parent_id=account_center_id,
            name="账号管理",
            route_path="/resources/accounts/manage",
            permission_key="resources.accounts.read",
            icon=None,
            sort_order=313,
        )
    )

    ids = {
        "menu_resources": resources_id,
        "menu_resources_account_center": account_center_id,
        "menu_marketing": _menu_id(bind, menus, "menu_marketing"),
    }
    for public_id, parent_key, name, menu_type, route, permission, sort_order in NEW_MENUS:
        result = bind.execute(
            menus.insert().values(
                public_id=public_id,
                parent_id=ids[parent_key],
                name=name,
                menu_type=menu_type,
                route_path=route,
                permission_key=permission,
                sort_order=sort_order,
                enabled=True,
                visible=True,
                is_builtin=True,
            )
        )
        ids[public_id] = int(result.inserted_primary_key[0])

    operations_id = ids["menu_resources_operations"]
    ip_id = _menu_id(bind, menus, "menu_resources_ip_management")
    bind.execute(
        menus.update().where(menus.c.id == ip_id).values(
            parent_id=operations_id,
            route_path="/resources/operations/ip",
            sort_order=322,
        )
    )

    new_ids = {ids[definition[0]] for definition in NEW_MENUS}
    account_ids = {
        resources_id,
        account_center_id,
        account_manage_id,
        ids["menu_resources_accounts_import"],
        ids["menu_resources_accounts_export"],
        ids["menu_resources_accounts_groups"],
        ids["menu_resources_accounts_statistics"],
    }
    group_ids = {
        ids[definition[0]]
        for definition in NEW_MENUS
        if definition[0].startswith("menu_marketing_group")
    }
    for role_id, system_key in bind.execute(
        sa.select(roles.c.id, roles.c.system_key)
    ).all():
        wanted = new_ids | {ip_id} if system_key == "admin" else (
            account_ids | group_ids if system_key == "operator" else set()
        )
        existing = set(
            bind.execute(
                sa.select(role_menus.c.menu_id).where(role_menus.c.role_id == role_id)
            ).scalars()
        )
        for menu_id in wanted - existing:
            bind.execute(role_menus.insert().values(role_id=role_id, menu_id=menu_id))
        if system_key in {"admin", "operator"}:
            existing_actions = set(
                bind.execute(
                    sa.select(role_actions.c.permission_key).where(
                        role_actions.c.role_id == role_id
                    )
                ).scalars()
            )
            for permission in set(NEW_ACTIONS) - existing_actions:
                bind.execute(
                    role_actions.insert().values(
                        role_id=role_id, permission_key=permission
                    )
                )


def downgrade() -> None:
    bind = op.get_bind()
    menus = sa.Table("system_menus", sa.MetaData(), autoload_with=bind)
    role_menus = sa.Table("role_menu_permissions", sa.MetaData(), autoload_with=bind)
    role_actions = sa.Table("role_action_permissions", sa.MetaData(), autoload_with=bind)

    new_public_ids = [definition[0] for definition in NEW_MENUS]
    new_ids = list(
        bind.execute(
            sa.select(menus.c.id).where(menus.c.public_id.in_(new_public_ids))
        ).scalars()
    )
    if new_ids:
        bind.execute(role_menus.delete().where(role_menus.c.menu_id.in_(new_ids)))
    bind.execute(
        role_actions.delete().where(
            role_actions.c.permission_key.in_(NEW_ACTIONS)
        )
    )

    ip_id = _menu_id(bind, menus, "menu_resources_ip_management")
    resources_id = _menu_id(bind, menus, "menu_resources")
    bind.execute(
        menus.update().where(menus.c.id == ip_id).values(
            parent_id=resources_id,
            route_path="/ip-management",
            sort_order=301,
        )
    )
    # Children must be removed before their new directory parents.
    for public_id in reversed(new_public_ids):
        bind.execute(menus.delete().where(menus.c.public_id == public_id))

    account_center_id = _menu_id(bind, menus, "menu_resources_account_center")
    account_manage_id = _menu_id(bind, menus, "menu_resources_accounts_manage")
    bind.execute(
        menus.update().where(menus.c.id == account_manage_id).values(
            public_id="menu_business_personal_accounts",
            parent_id=account_center_id,
            name="个人账号",
            route_path="/personal-accounts",
            permission_key="business.personal_accounts.read",
            icon="ContactRound",
            sort_order=11,
        )
    )
    bind.execute(
        menus.update().where(menus.c.id == account_center_id).values(
            public_id="menu_business",
            parent_id=None,
            name="业务",
            icon="BriefcaseBusiness",
            sort_order=10,
        )
    )
