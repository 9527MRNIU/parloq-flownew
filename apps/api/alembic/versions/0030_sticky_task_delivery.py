"""add sticky account slots and durable task delivery leases

Revision ID: 0030_sticky_task_delivery
Revises: 0029_channel_default_groups
Create Date: 2026-08-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0030_sticky_task_delivery"
down_revision = "0029_channel_default_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("personal_accounts") as batch:
        batch.add_column(sa.Column("sending_cooldown_until", sa.DateTime(timezone=True)))
        batch.create_index(
            "ix_personal_accounts_sending_cooldown_until",
            ["sending_cooldown_until"],
        )

    with op.batch_alter_table("data_packages") as batch:
        batch.add_column(
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(sa.Column("sealed_at", sa.DateTime(timezone=True)))
        batch.create_index("ix_data_packages_sealed_at", ["sealed_at"])

    with op.batch_alter_table("data_package_recipients") as batch:
        batch.add_column(
            sa.Column(
                "package_revision",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch.add_column(sa.Column("removed_revision", sa.Integer()))
        batch.add_column(
            sa.Column(
                "validation_status",
                sa.String(16),
                nullable=False,
                server_default="valid",
            )
        )
        batch.add_column(sa.Column("last_error", sa.Text()))
        batch.create_index(
            "ix_data_package_recipients_validation_status",
            ["validation_status"],
        )
        batch.create_index(
            "ix_data_package_recipients_package_revision",
            ["package_revision"],
        )
        batch.create_index(
            "ix_data_package_recipients_removed_revision",
            ["removed_revision"],
        )

    with op.batch_alter_table("hyperlink_tasks") as batch:
        batch.add_column(sa.Column("data_package_revision", sa.Integer()))
        batch.add_column(
            sa.Column("reconciling_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("cancelled_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("paused_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("cancelled_at", sa.DateTime(timezone=True)))

    op.create_table(
        "hyperlink_task_account_slots",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("slot_index", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.BigInteger()),
        sa.Column("status", sa.String(16), nullable=False, server_default="vacant"),
        sa.Column("lease_token", sa.String(64)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("acquired_at", sa.DateTime(timezone=True)),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("switch_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "consecutive_failure_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("last_switch_reason", sa.String(64)),
        sa.Column("last_error", sa.Text()),
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
            "status IN ('vacant', 'active', 'replacing', 'released')",
            name="ck_hyperlink_task_slot_status",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["personal_accounts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["hyperlink_tasks.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", name="uq_hyperlink_task_slot_account"),
        sa.UniqueConstraint(
            "task_id", "slot_index", name="uq_hyperlink_task_slot_index"
        ),
    )
    op.create_index(
        "ix_hyperlink_task_account_slots_task_id",
        "hyperlink_task_account_slots",
        ["task_id"],
    )
    op.create_index(
        "ix_hyperlink_task_account_slots_account_id",
        "hyperlink_task_account_slots",
        ["account_id"],
    )
    op.create_index(
        "ix_hyperlink_task_account_slots_status",
        "hyperlink_task_account_slots",
        ["status"],
    )
    op.create_index(
        "ix_hyperlink_task_account_slots_lease_token",
        "hyperlink_task_account_slots",
        ["lease_token"],
    )
    op.create_index(
        "ix_hyperlink_task_account_slots_lease_expires_at",
        "hyperlink_task_account_slots",
        ["lease_expires_at"],
    )

    with op.batch_alter_table("hyperlink_task_deliveries") as batch:
        batch.add_column(sa.Column("slot_id", sa.BigInteger()))
        batch.add_column(sa.Column("lease_token", sa.String(64)))
        batch.add_column(sa.Column("leased_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
        batch.create_foreign_key(
            "fk_hyperlink_task_deliveries_slot_id",
            "hyperlink_task_account_slots",
            ["slot_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_hyperlink_task_deliveries_slot_id", ["slot_id"])
        batch.create_index("ix_hyperlink_task_deliveries_lease_token", ["lease_token"])
        batch.create_index(
            "ix_hyperlink_task_deliveries_leased_at", ["leased_at"]
        )
        batch.create_index(
            "ix_hyperlink_task_deliveries_lease_expires_at", ["lease_expires_at"]
        )

    op.execute(
        """
        UPDATE hyperlink_tasks
           SET data_package_revision = COALESCE(
               (SELECT data_packages.revision
                  FROM data_packages
                 WHERE data_packages.id = hyperlink_tasks.data_package_id),
               1
           )
         WHERE data_package_revision IS NULL
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("hyperlink_task_deliveries") as batch:
        batch.drop_index("ix_hyperlink_task_deliveries_lease_expires_at")
        batch.drop_index("ix_hyperlink_task_deliveries_leased_at")
        batch.drop_index("ix_hyperlink_task_deliveries_lease_token")
        batch.drop_index("ix_hyperlink_task_deliveries_slot_id")
        batch.drop_constraint(
            "fk_hyperlink_task_deliveries_slot_id", type_="foreignkey"
        )
        batch.drop_column("lease_expires_at")
        batch.drop_column("leased_at")
        batch.drop_column("lease_token")
        batch.drop_column("slot_id")

    op.drop_table("hyperlink_task_account_slots")

    with op.batch_alter_table("hyperlink_tasks") as batch:
        batch.drop_column("cancelled_at")
        batch.drop_column("paused_at")
        batch.drop_column("cancelled_count")
        batch.drop_column("skipped_count")
        batch.drop_column("reconciling_count")
        batch.drop_column("data_package_revision")

    with op.batch_alter_table("data_package_recipients") as batch:
        batch.drop_index("ix_data_package_recipients_removed_revision")
        batch.drop_index("ix_data_package_recipients_package_revision")
        batch.drop_index("ix_data_package_recipients_validation_status")
        batch.drop_column("last_error")
        batch.drop_column("validation_status")
        batch.drop_column("removed_revision")
        batch.drop_column("package_revision")

    # SQLite batch mode would recreate and DROP the referenced data_packages
    # table while hyperlink_tasks still points at it. Modern SQLite supports
    # DROP COLUMN directly, so avoid the destructive table-copy path there.
    recreate_mode = "never" if op.get_bind().dialect.name == "sqlite" else "auto"
    with op.batch_alter_table("data_packages", recreate=recreate_mode) as batch:
        batch.drop_index("ix_data_packages_sealed_at")
        batch.drop_column("sealed_at")
        batch.drop_column("revision")

    with op.batch_alter_table("personal_accounts") as batch:
        batch.drop_index("ix_personal_accounts_sending_cooldown_until")
        batch.drop_column("sending_cooldown_until")
