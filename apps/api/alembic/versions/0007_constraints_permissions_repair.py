"""Repair constraints and permissions after already-published 0006 deployments."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op


revision: str = "0007_constraints_permissions"
down_revision: str | None = "0006_forward_repair"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OPERATOR_ACTIONS = {
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
}


def _columns(bind, table: str) -> dict[str, dict]:
    return {column["name"]: column for column in sa.inspect(bind).get_columns(table)}


def _add_column(bind, table: str, column: sa.Column) -> None:
    if column.name not in _columns(bind, table):
        op.add_column(table, column)


def _index_names(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table)} | {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(table)
        if constraint.get("name")
    }


def _ensure_index(bind, name: str, table: str, columns: list[str], *, unique=False) -> None:
    if name not in _index_names(bind, table):
        op.create_index(name, table, columns, unique=unique)


def _repair_columns(bind) -> None:
    _add_column(bind, "promotion_events", sa.Column("visitor_id", sa.String(80)))
    _ensure_index(bind, "ix_promotion_events_channel_visitor", "promotion_events", ["channel_id", "visitor_id"])
    _add_column(bind, "ad_metrics", sa.Column("other_cost", sa.Numeric(18, 6), nullable=False, server_default="0"))
    _add_column(bind, "user_groups", sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    _ensure_index(bind, "ix_user_groups_enabled", "user_groups", ["enabled"])
    for column in (
        sa.Column("acquisition_type", sa.String(16), nullable=False, server_default="connected"),
        sa.Column("management_mode", sa.String(16), nullable=False, server_default="external"),
        sa.Column("registrar_provider", sa.String(80)),
        sa.Column("registration_status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("hosting_provider", sa.String(80), nullable=False, server_default="cloudflare"),
        sa.Column("hosting_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("verification_token", sa.String(80)),
    ):
        _add_column(bind, "domains", column)
    domains = sa.Table("domains", sa.MetaData(), autoload_with=bind)
    for domain_id, token, dns_status, ssl_status in bind.execute(
        sa.select(domains.c.id, domains.c.verification_token, domains.c.dns_status, domains.c.ssl_status)
    ):
        values = {}
        if not token:
            values["verification_token"] = f"legacy-domain-{domain_id}"
        if dns_status == "verified" and ssl_status == "verified":
            values.update(registration_status="active", hosting_status="active")
        if values:
            bind.execute(domains.update().where(domains.c.id == domain_id).values(**values))
    _ensure_index(bind, "uq_domains_verification_token", "domains", ["verification_token"], unique=True)
    for column in ("acquisition_type", "management_mode", "registration_status", "expires_at", "hosting_status"):
        _ensure_index(bind, f"ix_domains_{column}", "domains", [column])


def _repair_order_constraints(bind) -> None:
    tables = set(sa.inspect(bind).get_table_names())
    if "domain_quotes" not in tables:
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
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    _add_column(bind, "domain_orders", sa.Column("quote_id", sa.Integer()))
    _add_column(bind, "domain_orders", sa.Column("last_reconciled_at", sa.DateTime(timezone=True)))
    quotes = sa.Table("domain_quotes", sa.MetaData(), autoload_with=bind)
    orders = sa.Table("domain_orders", sa.MetaData(), autoload_with=bind)
    for order in bind.execute(sa.select(orders)).mappings():
        if order.get("quote_id") is not None:
            continue
        quote_public_id = f"legacy_quote_{order['id']}"
        quote_id = bind.execute(sa.select(quotes.c.id).where(quotes.c.public_id == quote_public_id)).scalar_one_or_none()
        if quote_id is None:
            created_at = order.get("created_at") or datetime.now(UTC)
            result = bind.execute(
                quotes.insert().values(
                    public_id=quote_public_id,
                    hostname=order["hostname"],
                    years=order.get("years") or 1,
                    amount=order.get("amount") or 0,
                    currency=order.get("currency") or "USD",
                    provider=order.get("provider") or "legacy",
                    expires_at=created_at,
                    consumed_at=created_at,
                    created_by=order["created_by"],
                )
            )
            quote_id = result.inserted_primary_key[0]
        bind.execute(orders.update().where(orders.c.id == order["id"]).values(quote_id=quote_id))
    _ensure_index(bind, "ix_domain_orders_quote_id", "domain_orders", ["quote_id"], unique=True)

    status_checks = [
        check
        for check in sa.inspect(bind).get_check_constraints("domain_orders")
        if "status" in str(check.get("sqltext", "")).lower()
    ]
    old_status_check = next(
        (check for check in status_checks if "unknown" not in str(check.get("sqltext", "")).lower()),
        None,
    )
    condition = "status IN ('pending_payment', 'paid', 'provisioning', 'unknown', 'completed', 'failed', 'cancelled')"
    if old_status_check and old_status_check.get("name"):
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("domain_orders") as batch:
                batch.drop_constraint(old_status_check["name"], type_="check")
                batch.create_check_constraint("ck_domain_orders_status", condition)
        else:
            op.drop_constraint(old_status_check["name"], "domain_orders", type_="check")
            op.create_check_constraint("ck_domain_orders_status", "domain_orders", condition)
    elif not status_checks:
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("domain_orders") as batch:
                batch.create_check_constraint("ck_domain_orders_status", condition)
        else:
            op.create_check_constraint("ck_domain_orders_status", "domain_orders", condition)

    if bind.dialect.name != "sqlite":
        if _columns(bind, "domains")["verification_token"].get("nullable", True):
            op.alter_column("domains", "verification_token", existing_type=sa.String(80), nullable=False)
        if _columns(bind, "domain_orders")["quote_id"].get("nullable", True):
            op.alter_column("domain_orders", "quote_id", existing_type=sa.Integer(), nullable=False)
        quote_fk = any(
            tuple(fk.get("constrained_columns") or ()) == ("quote_id",)
            for fk in sa.inspect(bind).get_foreign_keys("domain_orders")
        )
        if not quote_fk:
            op.create_foreign_key(
                "fk_domain_orders_quote_id_domain_quotes",
                "domain_orders",
                "domain_quotes",
                ["quote_id"],
                ["id"],
                ondelete="RESTRICT",
            )
        domain_checks = {check.get("name") for check in sa.inspect(bind).get_check_constraints("domains")}
        for name, check_condition in (
            ("ck_domains_acquisition_type", "acquisition_type IN ('connected', 'purchased')"),
            ("ck_domains_management_mode", "management_mode IN ('external', 'platform')"),
            ("ck_domains_registration_status", "registration_status IN ('active', 'pending', 'failed', 'expired')"),
            ("ck_domains_hosting_status", "hosting_status IN ('pending', 'active', 'failed')"),
        ):
            if name not in domain_checks:
                op.create_check_constraint(name, "domains", check_condition)


def _repair_permissions_and_menu_contract(bind) -> None:
    tables = set(sa.inspect(bind).get_table_names())
    if "role_action_permissions" not in tables:
        op.create_table(
            "role_action_permissions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("role_id", sa.Integer(), sa.ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=False),
            sa.Column("permission_key", sa.String(120), nullable=False),
            sa.UniqueConstraint("role_id", "permission_key", name="uq_role_action_permission"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    menus = sa.Table("system_menus", sa.MetaData(), autoload_with=bind)
    role_menus = sa.Table("role_menu_permissions", sa.MetaData(), autoload_with=bind)
    role_actions = sa.Table("role_action_permissions", sa.MetaData(), autoload_with=bind)
    roles = sa.Table("user_groups", sa.MetaData(), autoload_with=bind)

    data_center_id = bind.execute(sa.select(menus.c.id).where(menus.c.public_id == "menu_promotion_data_center")).scalar_one_or_none()
    for old_id, public_id, name, route, permission, sort_order in (
        ("menu_promotion_overview", "menu_promotion_statistics", "渠道统计", "/promotion/statistics", "promotion.statistics.read", 121),
        ("menu_promotion_ad_metrics", "menu_promotion_trends", "趋势图", "/promotion/trends", "promotion.trends.read", 122),
    ):
        menu_id = bind.execute(sa.select(menus.c.id).where(menus.c.public_id == public_id)).scalar_one_or_none()
        if menu_id is None:
            menu_id = bind.execute(sa.select(menus.c.id).where(menus.c.public_id == old_id)).scalar_one_or_none()
        if menu_id is None and data_center_id is not None:
            menu_id = bind.execute(
                sa.select(menus.c.id).where(menus.c.parent_id == data_center_id, menus.c.sort_order == sort_order)
            ).scalar_one_or_none()
        if menu_id is not None:
            bind.execute(
                menus.update().where(menus.c.id == menu_id).values(
                    public_id=public_id,
                    name=name,
                    route_path=route,
                    permission_key=permission,
                )
            )
    domain_menu_id = bind.execute(sa.select(menus.c.id).where(menus.c.public_id == "menu_promotion_domains")).scalar_one_or_none()
    if domain_menu_id is not None:
        bind.execute(
            menus.update().where(menus.c.id == domain_menu_id).values(
                route_path="/promotion/domains", permission_key="promotion.domain.read"
            )
        )

    operator_menu_ids = set(
        bind.execute(
            sa.select(menus.c.id).where(
                sa.or_(
                    menus.c.public_id.like("menu_business%"),
                    menus.c.public_id.like("menu_promotion%"),
                    menus.c.public_id.like("menu_marketing%"),
                )
            )
        ).scalars()
    )
    all_builtin_ids = set(bind.execute(sa.select(menus.c.id).where(menus.c.is_builtin.is_(True))).scalars())
    for role_id, system_key in bind.execute(sa.select(roles.c.id, roles.c.system_key)):
        if system_key == "admin":
            wanted_menus = all_builtin_ids
            wanted_actions = OPERATOR_ACTIONS | {"resources.ip.manage"}
        elif system_key == "operator":
            wanted_menus = operator_menu_ids
            wanted_actions = OPERATOR_ACTIONS
        else:
            # Preserve explicit custom-role grants; never broaden them during
            # a forward schema/contract repair.
            continue
        existing_menus = set(bind.execute(sa.select(role_menus.c.menu_id).where(role_menus.c.role_id == role_id)).scalars())
        for menu_id in wanted_menus - existing_menus:
            bind.execute(role_menus.insert().values(role_id=role_id, menu_id=menu_id))
        existing_actions = set(bind.execute(sa.select(role_actions.c.permission_key).where(role_actions.c.role_id == role_id)).scalars())
        for permission_key in wanted_actions - existing_actions:
            bind.execute(role_actions.insert().values(role_id=role_id, permission_key=permission_key))


def upgrade() -> None:
    bind = op.get_bind()
    _repair_columns(bind)
    _repair_order_constraints(bind)
    _repair_permissions_and_menu_contract(bind)


def downgrade() -> None:
    pass
