"""Add menu permissions, managed domain orders and domain lifecycle metadata."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0005_system_promotion_domains"
down_revision: str | None = "0004_tenant_ownership_async"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    # Use SQLite-native ADD COLUMN operations. Rebuilding user_groups/domains in
    # batch mode would require dropping tables that are referenced by live FKs.
    op.add_column(
        "user_groups",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_user_groups_enabled", "user_groups", ["enabled"])
    op.add_column("promotion_events", sa.Column("visitor_id", sa.String(80)))
    op.create_index(
        "ix_promotion_events_channel_visitor",
        "promotion_events",
        ["channel_id", "visitor_id"],
    )
    op.add_column(
        "ad_metrics",
        sa.Column("other_cost", sa.Numeric(18, 6), nullable=False, server_default="0"),
    )

    op.create_table(
        "system_menus",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "parent_id",
            sa.Integer(),
            sa.ForeignKey("system_menus.id", ondelete="RESTRICT"),
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("menu_type", sa.String(16), nullable=False, server_default="page"),
        sa.Column("route_path", sa.String(255), unique=True),
        sa.Column("icon", sa.String(80)),
        sa.Column("permission_key", sa.String(120), unique=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("visible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint(
            "menu_type IN ('directory', 'page')", name="ck_system_menus_type"
        ),
        *_timestamps(),
    )
    for column in ("public_id", "parent_id", "name", "permission_key", "enabled"):
        op.create_index(f"ix_system_menus_{column}", "system_menus", [column])

    op.create_table(
        "role_menu_permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "role_id",
            sa.Integer(),
            sa.ForeignKey("user_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "menu_id",
            sa.Integer(),
            sa.ForeignKey("system_menus.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("role_id", "menu_id", name="uq_role_menu_permission"),
        *_timestamps(),
    )
    op.create_index("ix_role_menu_permissions_role_id", "role_menu_permissions", ["role_id"])
    op.create_index("ix_role_menu_permissions_menu_id", "role_menu_permissions", ["menu_id"])

    op.create_table(
        "role_action_permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "role_id",
            sa.Integer(),
            sa.ForeignKey("user_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("permission_key", sa.String(120), nullable=False),
        sa.UniqueConstraint(
            "role_id", "permission_key", name="uq_role_action_permission"
        ),
        *_timestamps(),
    )
    op.create_index(
        "ix_role_action_permissions_role_id", "role_action_permissions", ["role_id"]
    )
    op.create_index(
        "ix_role_action_permissions_permission_key",
        "role_action_permissions",
        ["permission_key"],
    )

    op.add_column(
        "domains",
        sa.Column(
            "acquisition_type", sa.String(16), nullable=False, server_default="connected"
        ),
    )
    op.add_column(
        "domains",
        sa.Column(
            "management_mode", sa.String(16), nullable=False, server_default="external"
        ),
    )
    op.add_column("domains", sa.Column("registrar_provider", sa.String(80)))
    op.add_column(
        "domains",
        sa.Column(
            "registration_status", sa.String(16), nullable=False, server_default="active"
        ),
    )
    op.add_column("domains", sa.Column("expires_at", sa.DateTime(timezone=True)))
    op.add_column(
        "domains",
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "domains",
        sa.Column(
            "hosting_provider", sa.String(80), nullable=False, server_default="cloudflare"
        ),
    )
    op.add_column(
        "domains",
        sa.Column(
            "hosting_status", sa.String(16), nullable=False, server_default="pending"
        ),
    )
    op.add_column("domains", sa.Column("verification_token", sa.String(80)))
    for column in (
        "acquisition_type",
        "management_mode",
        "registration_status",
        "expires_at",
        "hosting_status",
    ):
        op.create_index(f"ix_domains_{column}", "domains", [column])

    op.execute(
        sa.text(
            "UPDATE domains SET verification_token = "
            "'legacy-domain-' || CAST(id AS VARCHAR) WHERE verification_token IS NULL"
        )
    )
    op.create_index(
        "uq_domains_verification_token",
        "domains",
        ["verification_token"],
        unique=True,
    )

    op.create_table(
        "domain_quotes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(64), nullable=False, unique=True),
        sa.Column("hostname", sa.String(255), nullable=False),
        sa.Column("years", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("user_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        *_timestamps(),
    )
    for column in ("public_id", "hostname", "expires_at", "created_by"):
        op.create_index(f"ix_domain_quotes_{column}", "domain_quotes", [column])

    op.create_table(
        "domain_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "quote_id",
            sa.Integer(),
            sa.ForeignKey("domain_quotes.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("hostname", sa.String(255), nullable=False),
        sa.Column("years", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column(
            "status", sa.String(24), nullable=False, server_default="pending_payment"
        ),
        sa.Column("provider", sa.String(80), nullable=False, server_default="mock"),
        sa.Column("provider_order_ref", sa.String(160), unique=True),
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("failure_reason", sa.Text()),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("last_reconciled_at", sa.DateTime(timezone=True)),
        sa.Column(
            "domain_id",
            sa.Integer(),
            sa.ForeignKey("domains.id", ondelete="SET NULL"),
            unique=True,
        ),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("user_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending_payment', 'paid', 'provisioning', 'unknown', 'completed', 'failed', 'cancelled')",
            name="ck_domain_orders_status",
        ),
        sa.CheckConstraint("years >= 1 AND years <= 10", name="ck_domain_orders_years"),
        sa.CheckConstraint("amount >= 0", name="ck_domain_orders_amount"),
        *_timestamps(),
    )
    for column in ("public_id", "quote_id", "hostname", "status", "domain_id", "created_by"):
        op.create_index(f"ix_domain_orders_{column}", "domain_orders", [column])

    menus = sa.table(
        "system_menus",
        sa.column("id", sa.Integer()),
        sa.column("public_id", sa.String()),
        sa.column("parent_id", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("menu_type", sa.String()),
        sa.column("route_path", sa.String()),
        sa.column("icon", sa.String()),
        sa.column("permission_key", sa.String()),
        sa.column("sort_order", sa.Integer()),
        sa.column("enabled", sa.Boolean()),
        sa.column("visible", sa.Boolean()),
        sa.column("is_builtin", sa.Boolean()),
    )
    bind = op.get_bind()

    def add_menu(
        public_id: str,
        name: str,
        menu_type: str,
        sort_order: int,
        *,
        parent_id: int | None = None,
        route_path: str | None = None,
        permission_key: str | None = None,
        icon: str | None = None,
    ) -> int:
        bind.execute(
            menus.insert().values(
                public_id=public_id,
                parent_id=parent_id,
                name=name,
                menu_type=menu_type,
                route_path=route_path,
                icon=icon,
                permission_key=permission_key,
                sort_order=sort_order,
                enabled=True,
                visible=True,
                is_builtin=True,
            )
        )
        return int(
            bind.execute(sa.select(menus.c.id).where(menus.c.public_id == public_id)).scalar_one()
        )

    business = add_menu("menu_business", "业务", "directory", 10, icon="BriefcaseBusiness")
    add_menu(
        "menu_business_personal_accounts",
        "个人账号",
        "page",
        11,
        parent_id=business,
        route_path="/personal-accounts",
        permission_key="business.personal_accounts.read",
        icon="ContactRound",
    )

    promotion = add_menu("menu_promotion", "推广", "directory", 100, icon="Megaphone")
    management = add_menu(
        "menu_promotion_management", "推广管理", "directory", 110, parent_id=promotion
    )
    add_menu(
        "menu_promotion_templates",
        "模板管理",
        "page",
        111,
        parent_id=management,
        route_path="/promotion/templates",
        permission_key="promotion.templates.read",
        icon="LayoutTemplate",
    )
    add_menu(
        "menu_promotion_channels",
        "渠道管理",
        "page",
        112,
        parent_id=management,
        route_path="/promotion/channels",
        permission_key="promotion.channels.read",
        icon="PanelsTopLeft",
    )
    add_menu(
        "menu_promotion_domains",
        "域名管理",
        "page",
        113,
        parent_id=management,
        route_path="/promotion/domains",
        permission_key="promotion.domain.read",
        icon="Globe2",
    )
    data_center = add_menu(
        "menu_promotion_data_center", "数据中心", "directory", 120, parent_id=promotion
    )
    add_menu(
        "menu_promotion_statistics",
        "渠道统计",
        "page",
        121,
        parent_id=data_center,
        route_path="/promotion/statistics",
        permission_key="promotion.statistics.read",
        icon="ChartNoAxesCombined",
    )
    add_menu(
        "menu_promotion_trends",
        "趋势图",
        "page",
        122,
        parent_id=data_center,
        route_path="/promotion/trends",
        permission_key="promotion.trends.read",
        icon="TableProperties",
    )

    marketing = add_menu("menu_marketing", "营销", "directory", 200, icon="Send")
    hyperlink = add_menu(
        "menu_marketing_hyperlink", "超链营销", "directory", 210, parent_id=marketing
    )
    add_menu(
        "menu_marketing_hyperlink_tasks",
        "超链任务",
        "page",
        211,
        parent_id=hyperlink,
        route_path="/hyperlink/tasks",
        permission_key="marketing.hyperlink_tasks.read",
    )
    add_menu(
        "menu_marketing_data_packages",
        "数据包",
        "page",
        212,
        parent_id=hyperlink,
        route_path="/hyperlink/data-packages",
        permission_key="marketing.data_packages.read",
    )
    add_menu(
        "menu_marketing_hyperlink_templates",
        "超链模板",
        "page",
        213,
        parent_id=hyperlink,
        route_path="/hyperlink/templates",
        permission_key="marketing.hyperlink_templates.read",
    )
    add_menu(
        "menu_marketing_hyperlink_strategies",
        "超链策略",
        "page",
        214,
        parent_id=hyperlink,
        route_path="/hyperlink/strategies",
        permission_key="marketing.hyperlink_strategies.read",
    )
    add_menu(
        "menu_marketing_materials",
        "素材库",
        "page",
        215,
        parent_id=hyperlink,
        route_path="/hyperlink/materials",
        permission_key="marketing.materials.read",
    )
    add_menu(
        "menu_marketing_insights",
        "市场透视",
        "page",
        216,
        parent_id=hyperlink,
        route_path="/hyperlink/market-insights",
        permission_key="marketing.insights.read",
    )
    add_menu(
        "menu_marketing_direct_short_links",
        "直接短链",
        "page",
        220,
        parent_id=marketing,
        route_path="/direct-short-links",
        permission_key="marketing.direct_short_links.read",
        icon="Link2",
    )

    resources = add_menu("menu_resources", "资源", "directory", 300, icon="Blocks")
    add_menu(
        "menu_resources_ip_management",
        "IP 管理",
        "page",
        301,
        parent_id=resources,
        route_path="/ip-management",
        permission_key="resources.ip.manage",
        icon="Network",
    )
    system = add_menu("menu_system", "系统管理", "directory", 900, icon="Settings")
    add_menu(
        "menu_system_users",
        "用户管理",
        "page",
        901,
        parent_id=system,
        route_path="/system/users",
        permission_key="system.users.manage",
        icon="Users",
    )
    add_menu(
        "menu_system_roles",
        "角色管理",
        "page",
        902,
        parent_id=system,
        route_path="/system/roles",
        permission_key="system.roles.manage",
        icon="ShieldCheck",
    )
    add_menu(
        "menu_system_menus",
        "菜单管理",
        "page",
        903,
        parent_id=system,
        route_path="/system/menus",
        permission_key="system.menus.manage",
        icon="ListTree",
    )

    roles = sa.table(
        "user_groups", sa.column("id", sa.Integer()), sa.column("system_key", sa.String())
    )
    permissions = sa.table(
        "role_menu_permissions",
        sa.column("role_id", sa.Integer()),
        sa.column("menu_id", sa.Integer()),
    )
    action_permissions = sa.table(
        "role_action_permissions",
        sa.column("role_id", sa.Integer()),
        sa.column("permission_key", sa.String()),
    )
    operator_actions = (
        "business.personal_accounts.manage",
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
    )
    menu_rows = bind.execute(sa.select(menus.c.id, menus.c.public_id)).all()
    admin_role_id = bind.execute(
        sa.select(roles.c.id).where(roles.c.system_key == "admin")
    ).scalar_one_or_none()
    operator_role_id = bind.execute(
        sa.select(roles.c.id).where(roles.c.system_key == "operator")
    ).scalar_one_or_none()
    if admin_role_id is not None:
        bind.execute(
            permissions.insert(),
            [{"role_id": admin_role_id, "menu_id": row.id} for row in menu_rows],
        )
        bind.execute(
            action_permissions.insert(),
            [
                {"role_id": admin_role_id, "permission_key": key}
                for key in (*operator_actions, "resources.ip.manage")
            ],
        )
    if operator_role_id is not None:
        bind.execute(
            permissions.insert(),
            [
                {"role_id": operator_role_id, "menu_id": row.id}
                for row in menu_rows
                if row.public_id.startswith(
                    ("menu_business", "menu_promotion", "menu_marketing")
                )
            ],
        )
        bind.execute(
            action_permissions.insert(),
            [
                {"role_id": operator_role_id, "permission_key": key}
                for key in operator_actions
            ],
        )


def downgrade() -> None:
    op.drop_table("domain_orders")
    op.drop_table("domain_quotes")
    for index in (
        "uq_domains_verification_token",
        "ix_domains_expires_at",
        "ix_domains_hosting_status",
        "ix_domains_registration_status",
        "ix_domains_management_mode",
        "ix_domains_acquisition_type",
    ):
        op.drop_index(index, table_name="domains")
    for column in (
        "verification_token",
        "hosting_status",
        "hosting_provider",
        "auto_renew",
        "expires_at",
        "registration_status",
        "registrar_provider",
        "management_mode",
        "acquisition_type",
    ):
        op.drop_column("domains", column)
    op.drop_table("role_action_permissions")
    op.drop_table("role_menu_permissions")
    # SQLite enforces the self-referencing parent FK while dropping the table.
    op.execute(sa.text("UPDATE system_menus SET parent_id = NULL"))
    op.execute(sa.text("DELETE FROM system_menus"))
    op.drop_table("system_menus")
    op.drop_column("ad_metrics", "other_cost")
    op.drop_index("ix_promotion_events_channel_visitor", table_name="promotion_events")
    op.drop_column("promotion_events", "visitor_id")
    op.drop_index("ix_user_groups_enabled", table_name="user_groups")
    op.drop_column("user_groups", "enabled")
