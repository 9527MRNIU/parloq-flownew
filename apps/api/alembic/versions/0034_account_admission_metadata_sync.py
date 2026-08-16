"""separate account admission from pairing and add durable metadata sync jobs

Revision ID: 0034_account_admission_sync
Revises: 0033_white_label_templates
Create Date: 2026-08-17
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op


revision = "0034_account_admission_sync"
down_revision = "0033_white_label_templates"
branch_labels = None
depends_on = None

EPOCH_MS = int(datetime(2026, 8, 1, tzinfo=UTC).timestamp() * 1000)
MIGRATION_NODE_ID = 1023


def _id_tables(connection: sa.Connection) -> tuple[str, ...]:
    inspector = sa.inspect(connection)
    return tuple(
        table
        for table in inspector.get_table_names()
        if any(column["name"] == "id" for column in inspector.get_columns(table))
    )


def _next_snowflake_id(
    connection: sa.Connection,
    id_tables: tuple[str, ...],
    *,
    offset: int,
) -> int:
    timestamp_ms = max(int(datetime.now(UTC).timestamp() * 1000), EPOCH_MS)
    while True:
        candidate = (
            ((timestamp_ms + offset // 4096 - EPOCH_MS) << 22)
            | (MIGRATION_NODE_ID << 12)
            | (offset % 4096)
        )
        if not any(
            connection.execute(
                sa.text(f'SELECT 1 FROM "{table}" WHERE id = :id LIMIT 1'),
                {"id": candidate},
            ).first()
            for table in id_tables
        ):
            return candidate
        offset += 1


def upgrade() -> None:
    connection = op.get_bind()
    sqlite = connection.dialect.name == "sqlite"
    recreate_mode = "never" if sqlite else "auto"

    with op.batch_alter_table("personal_accounts", recreate=recreate_mode) as batch:
        batch.add_column(
            sa.Column(
                "admission_status",
                sa.String(16),
                nullable=False,
                server_default="active",
            )
        )
        if not sqlite:
            batch.create_check_constraint(
                "ck_personal_accounts_admission_status",
                "admission_status IN ('reserved', 'active', 'abandoned')",
            )
        batch.create_index(
            "ix_personal_accounts_admission_status", ["admission_status"]
        )

    # Older landing-page rows that never reached a verified terminal state are
    # attempts, not members of the formal account pool. Preserve verified and
    # imported accounts as active; keep a currently live attempt reserved.
    connection.execute(
        sa.text(
            """
            UPDATE personal_accounts
               SET admission_status = 'abandoned'
             WHERE source = 'landing_page'
               AND validation_status != 'ready'
               AND NOT EXISTS (
                   SELECT 1
                     FROM account_pairing_attempts
                    WHERE account_pairing_attempts.account_id = personal_accounts.id
                      AND account_pairing_attempts.status = 'verified'
               )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE personal_accounts
               SET admission_status = 'reserved'
             WHERE source = 'landing_page'
               AND validation_status != 'ready'
               AND EXISTS (
                   SELECT 1
                     FROM account_pairing_attempts
                    WHERE account_pairing_attempts.account_id = personal_accounts.id
                      AND account_pairing_attempts.status IN
                          ('code_issued', 'waiting_phone', 'reconnecting')
               )
            """
        )
    )

    with op.batch_alter_table(
        "account_pairing_attempts", recreate=recreate_mode
    ) as batch:
        batch.add_column(
            sa.Column(
                "attempt_type",
                sa.String(24),
                nullable=False,
                server_default="initial",
            )
        )
        if not sqlite:
            batch.create_check_constraint(
                "ck_account_pairing_attempts_type",
                "attempt_type IN ('initial', 'reauthentication')",
            )
        batch.create_index(
            "ix_account_pairing_attempts_attempt_type", ["attempt_type"]
        )

    op.create_table(
        "account_metadata_sync_jobs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("protocol_node_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "sync_policy_version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "sync_policy_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("active_key", sa.String(80)),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column(
            "result_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_account_metadata_sync_jobs_status",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["personal_accounts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["protocol_node_id"], ["protocol_nodes.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["user_accounts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("active_key"),
    )
    for column in (
        "public_id",
        "account_id",
        "protocol_node_id",
        "status",
        "active_key",
        "created_by",
    ):
        op.create_index(
            f"ix_account_metadata_sync_jobs_{column}",
            "account_metadata_sync_jobs",
            [column],
        )
    op.create_index(
        "ix_account_metadata_sync_jobs_pending",
        "account_metadata_sync_jobs",
        ["status", "created_at"],
    )

    menus = sa.Table("system_menus", sa.MetaData(), autoload_with=connection)
    role_menus = sa.Table(
        "role_menu_permissions", sa.MetaData(), autoload_with=connection
    )
    roles = sa.Table("user_groups", sa.MetaData(), autoload_with=connection)
    account_center_id = connection.execute(
        sa.select(menus.c.id).where(
            menus.c.public_id == "menu_resources_account_center"
        )
    ).scalar_one()
    id_tables = _id_tables(connection)
    menu_id = _next_snowflake_id(connection, id_tables, offset=0)
    connection.execute(
        menus.insert().values(
            id=menu_id,
            public_id="menu_resources_account_intake",
            parent_id=account_center_id,
            name="接入记录",
            menu_type="page",
            route_path="/resources/accounts/intake",
            permission_key="resources.account_intake.read",
            sort_order=314,
            enabled=True,
            visible=True,
            is_builtin=True,
        )
    )
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_resources_accounts_export")
        .values(sort_order=315)
    )
    for offset, role_id in enumerate(
        connection.execute(
            sa.select(roles.c.id).where(
                roles.c.system_key.in_(("admin", "operator"))
            )
        ).scalars(),
        start=1,
    ):
        connection.execute(
            role_menus.insert().values(
                id=_next_snowflake_id(connection, id_tables, offset=offset),
                role_id=role_id,
                menu_id=menu_id,
            )
        )


def downgrade() -> None:
    connection = op.get_bind()
    menu_id = connection.execute(
        sa.text(
            "SELECT id FROM system_menus "
            "WHERE public_id = 'menu_resources_account_intake'"
        )
    ).scalar_one_or_none()
    if menu_id is not None:
        connection.execute(
            sa.text("DELETE FROM role_menu_permissions WHERE menu_id = :menu_id"),
            {"menu_id": menu_id},
        )
        connection.execute(
            sa.text("DELETE FROM system_menus WHERE id = :menu_id"),
            {"menu_id": menu_id},
        )
    connection.execute(
        sa.text(
            "UPDATE system_menus SET sort_order = 314 "
            "WHERE public_id = 'menu_resources_accounts_export'"
        )
    )
    op.drop_table("account_metadata_sync_jobs")
    sqlite = connection.dialect.name == "sqlite"
    recreate_mode = "never" if sqlite else "auto"
    with op.batch_alter_table(
        "account_pairing_attempts", recreate=recreate_mode
    ) as batch:
        batch.drop_index("ix_account_pairing_attempts_attempt_type")
        if not sqlite:
            batch.drop_constraint(
                "ck_account_pairing_attempts_type", type_="check"
            )
        batch.drop_column("attempt_type")
    with op.batch_alter_table("personal_accounts", recreate=recreate_mode) as batch:
        batch.drop_index("ix_personal_accounts_admission_status")
        if not sqlite:
            batch.drop_constraint(
                "ck_personal_accounts_admission_status", type_="check"
            )
        batch.drop_column("admission_status")
