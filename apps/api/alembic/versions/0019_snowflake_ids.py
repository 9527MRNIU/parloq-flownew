"""use 64-bit Snowflake IDs for internal and public entities

Revision ID: 0019_snowflake_ids
Revises: 0018_strict_template_defaults
Create Date: 2026-08-14
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op


revision = "0019_snowflake_ids"
down_revision = "0018_strict_template_defaults"
branch_labels = None
depends_on = None


EPOCH_MS = int(datetime(2026, 8, 1, tzinfo=UTC).timestamp() * 1000)
MIGRATION_NODE_ID = 1023

ID_TABLES = (
    "user_groups",
    "user_accounts",
    "auth_sessions",
    "system_menus",
    "role_menu_permissions",
    "role_action_permissions",
    "bitly_provider_accounts",
    "direct_short_links",
    "meta_pixels",
    "proxy_endpoints",
    "ip_allocation_policies",
    "account_proxy_bindings",
    "account_groups",
    "protocol_nodes",
    "personal_accounts",
    "account_lifecycle_events",
    "account_analytics_state",
    "message_deliveries",
    "domains",
    "domain_quotes",
    "domain_orders",
    "promotion_templates",
    "promotion_template_policies",
    "promotion_assets",
    "promotion_channels",
    "promotion_leads",
    "promotion_events",
    "hyperlink_materials",
    "hyperlink_templates",
    "hyperlink_strategies",
    "data_packages",
    "data_package_recipients",
    "hyperlink_tasks",
    "hyperlink_task_deliveries",
    "ad_metrics",
)


def _existing_tables(bind: sa.Connection) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _foreign_keys(bind: sa.Connection, tables: set[str]) -> list[dict]:
    result: list[dict] = []
    inspector = sa.inspect(bind)
    for table in ID_TABLES:
        if table not in tables:
            continue
        for foreign_key in inspector.get_foreign_keys(table):
            referred = foreign_key.get("referred_table")
            if referred not in tables:
                continue
            result.append({"table": table, **foreign_key})
    return result


def _drop_foreign_keys(foreign_keys: list[dict]) -> None:
    for foreign_key in foreign_keys:
        name = foreign_key.get("name")
        if not name:
            raise RuntimeError(
                f"foreign key on {foreign_key['table']} has no stable constraint name"
            )
        op.drop_constraint(name, foreign_key["table"], type_="foreignkey")


def _create_foreign_keys(foreign_keys: list[dict]) -> None:
    for foreign_key in foreign_keys:
        options = foreign_key.get("options") or {}
        op.create_foreign_key(
            foreign_key["name"],
            foreign_key["table"],
            foreign_key["referred_table"],
            foreign_key["constrained_columns"],
            foreign_key["referred_columns"],
            onupdate=options.get("onupdate"),
            ondelete=options.get("ondelete"),
            deferrable=options.get("deferrable"),
            initially=options.get("initially"),
        )


def _alter_id_columns(
    foreign_keys: list[dict], tables: set[str], target: sa.types.TypeEngine
) -> None:
    upgrading = isinstance(target, sa.BigInteger)
    columns_by_table: dict[str, set[str]] = {
        table: {"id"} for table in ID_TABLES if table in tables
    }
    for foreign_key in foreign_keys:
        columns_by_table[foreign_key["table"]].update(
            foreign_key["constrained_columns"]
        )
    for table, columns in columns_by_table.items():
        for column in sorted(columns):
            op.alter_column(
                table,
                column,
                existing_type=sa.Integer() if upgrading else sa.BigInteger(),
                type_=target,
                postgresql_using=f'"{column}"::bigint'
                if upgrading
                else f'"{column}"::integer',
            )


def _snowflake_values(count: int) -> list[int]:
    now_ms = max(int(datetime.now(UTC).timestamp() * 1000), EPOCH_MS)
    result: list[int] = []
    for offset in range(count):
        timestamp_ms = now_ms + (offset // 4096)
        sequence = offset % 4096
        result.append(
            ((timestamp_ms - EPOCH_MS) << 22)
            | (MIGRATION_NODE_ID << 12)
            | sequence
        )
    return result


def _remap_ids(
    bind: sa.Connection,
    tables: set[str],
    foreign_keys: list[dict],
    *,
    snowflake: bool,
) -> None:
    mappings: dict[str, dict[int, int]] = {}
    total = sum(
        int(bind.execute(sa.text(f'SELECT count(*) FROM "{table}"')).scalar_one())
        for table in ID_TABLES
        if table in tables
    )
    snowflakes = iter(_snowflake_values(total)) if snowflake else iter(())

    for table in ID_TABLES:
        if table not in tables:
            continue
        old_ids = [
            int(row[0])
            for row in bind.execute(sa.text(f'SELECT id FROM "{table}" ORDER BY id'))
        ]
        mappings[table] = {
            old_id: next(snowflakes) if snowflake else index
            for index, old_id in enumerate(old_ids, start=1)
        }

    for table, mapping in mappings.items():
        for old_id, new_id in mapping.items():
            bind.execute(
                sa.text(f'UPDATE "{table}" SET id=:new_id WHERE id=:old_id'),
                {"new_id": new_id, "old_id": old_id},
            )

    for foreign_key in foreign_keys:
        referred_table = foreign_key["referred_table"]
        mapping = mappings.get(referred_table, {})
        for local_column, _remote_column in zip(
            foreign_key["constrained_columns"],
            foreign_key["referred_columns"],
            strict=True,
        ):
            for old_id, new_id in mapping.items():
                bind.execute(
                    sa.text(
                        f'UPDATE "{foreign_key["table"]}" '
                        f'SET "{local_column}"=:new_id '
                        f'WHERE "{local_column}"=:old_id'
                    ),
                    {"new_id": new_id, "old_id": old_id},
                )


def _upgrade_analytics_state(bind: sa.Connection, tables: set[str]) -> None:
    if "account_analytics_state" not in tables:
        return
    inspector = sa.inspect(bind)
    checks = {item["name"] for item in inspector.get_check_constraints("account_analytics_state")}
    if "ck_account_analytics_state_singleton" in checks:
        op.drop_constraint(
            "ck_account_analytics_state_singleton",
            "account_analytics_state",
            type_="check",
        )
    op.add_column(
        "account_analytics_state",
        sa.Column(
            "singleton_key",
            sa.String(length=16),
            nullable=False,
            server_default="global",
        ),
    )
    op.create_unique_constraint(
        "uq_account_analytics_state_singleton_key",
        "account_analytics_state",
        ["singleton_key"],
    )
    op.create_check_constraint(
        "ck_account_analytics_state_singleton",
        "account_analytics_state",
        "singleton_key = 'global'",
    )


def upgrade() -> None:
    bind = op.get_bind()
    tables = _existing_tables(bind)
    dialect = bind.dialect.name
    foreign_keys = _foreign_keys(bind, tables)

    if dialect == "postgresql":
        _drop_foreign_keys(foreign_keys)
        _upgrade_analytics_state(bind, tables)
        _alter_id_columns(foreign_keys, tables, sa.BigInteger())
        _remap_ids(bind, tables, foreign_keys, snowflake=True)
        _create_foreign_keys(foreign_keys)
        return

    # SQLite INTEGER already stores signed 64-bit values. Avoid destructive table
    # recreation in tests while still installing the singleton key used by the ORM.
    if "account_analytics_state" in tables:
        with op.batch_alter_table("account_analytics_state") as batch_op:
            batch_op.drop_constraint(
                "ck_account_analytics_state_singleton", type_="check"
            )
            batch_op.add_column(
                sa.Column(
                    "singleton_key",
                    sa.String(length=16),
                    nullable=False,
                    server_default="global",
                )
            )
            batch_op.create_unique_constraint(
                "uq_account_analytics_state_singleton_key", ["singleton_key"]
            )
            batch_op.create_check_constraint(
                "ck_account_analytics_state_singleton", "singleton_key = 'global'"
            )


def downgrade() -> None:
    bind = op.get_bind()
    tables = _existing_tables(bind)
    dialect = bind.dialect.name
    foreign_keys = _foreign_keys(bind, tables)

    if dialect == "postgresql":
        _drop_foreign_keys(foreign_keys)
        if "account_analytics_state" in tables:
            op.drop_constraint(
                "ck_account_analytics_state_singleton",
                "account_analytics_state",
                type_="check",
            )
        _remap_ids(bind, tables, foreign_keys, snowflake=False)
        _alter_id_columns(foreign_keys, tables, sa.Integer())
        _create_foreign_keys(foreign_keys)
        if "account_analytics_state" in tables:
            op.drop_constraint(
                "uq_account_analytics_state_singleton_key",
                "account_analytics_state",
                type_="unique",
            )
            op.drop_column("account_analytics_state", "singleton_key")
            op.create_check_constraint(
                "ck_account_analytics_state_singleton",
                "account_analytics_state",
                "id = 1",
            )
        return

    if "account_analytics_state" in tables:
        with op.batch_alter_table("account_analytics_state") as batch_op:
            batch_op.drop_constraint(
                "ck_account_analytics_state_singleton", type_="check"
            )
            batch_op.drop_constraint(
                "uq_account_analytics_state_singleton_key", type_="unique"
            )
            batch_op.drop_column("singleton_key")
            batch_op.create_check_constraint(
                "ck_account_analytics_state_singleton", "id = 1"
            )
