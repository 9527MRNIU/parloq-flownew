"""Add the unified account pool, import provenance and quality metadata."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0010_unified_account_pool"
down_revision: str | None = "0009_channel_host_slug_leads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "account_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("user_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("created_by", "name", name="uq_account_groups_owner_name"),
    )
    for column in ("public_id", "name", "archived_at", "created_by"):
        op.create_index(f"ix_account_groups_{column}", "account_groups", [column])

    with op.batch_alter_table("personal_accounts") as batch:
        batch.add_column(
            sa.Column(
                "source",
                sa.String(24),
                nullable=False,
                server_default="landing_page",
            )
        )
        batch.add_column(sa.Column("source_ref_type", sa.String(40)))
        batch.add_column(sa.Column("source_ref_id", sa.String(64)))
        batch.add_column(sa.Column("import_format", sa.String(40)))
        batch.add_column(
            sa.Column(
                "validation_status",
                sa.String(16),
                nullable=False,
                server_default="pending",
            )
        )
        batch.add_column(
            sa.Column(
                "metadata_sync_status",
                sa.String(16),
                nullable=False,
                server_default="pending",
            )
        )
        batch.add_column(sa.Column("group_id", sa.Integer()))
        batch.add_column(sa.Column("has_avatar", sa.Boolean()))
        batch.add_column(sa.Column("group_count", sa.Integer()))
        batch.add_column(sa.Column("friend_count", sa.Integer()))
        batch.add_column(sa.Column("mutual_contact_count", sa.Integer()))
        batch.add_column(sa.Column("quality_synced_at", sa.DateTime(timezone=True)))
        batch.create_foreign_key(
            "fk_personal_accounts_group_id_account_groups",
            "account_groups",
            ["group_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_check_constraint(
            "ck_personal_accounts_source",
            "source IN ('landing_page', 'json_import')",
        )
        batch.create_check_constraint(
            "ck_personal_accounts_validation_status",
            "validation_status IN ('pending', 'validating', 'ready', 'failed')",
        )
        batch.create_check_constraint(
            "ck_personal_accounts_metadata_sync_status",
            "metadata_sync_status IN ('pending', 'syncing', 'ready', 'failed', 'unsupported')",
        )

    op.execute(
        sa.text(
            "UPDATE personal_accounts SET validation_status = 'ready' "
            "WHERE status NOT IN ('unpaired', 'pairing', 'disabled')"
        )
    )
    for column in (
        "source",
        "source_ref_type",
        "source_ref_id",
        "import_format",
        "validation_status",
        "metadata_sync_status",
        "group_id",
    ):
        op.create_index(f"ix_personal_accounts_{column}", "personal_accounts", [column])


def downgrade() -> None:
    for column in (
        "group_id",
        "metadata_sync_status",
        "validation_status",
        "import_format",
        "source_ref_id",
        "source_ref_type",
        "source",
    ):
        op.drop_index(f"ix_personal_accounts_{column}", table_name="personal_accounts")
    with op.batch_alter_table("personal_accounts") as batch:
        batch.drop_constraint("ck_personal_accounts_metadata_sync_status", type_="check")
        batch.drop_constraint("ck_personal_accounts_validation_status", type_="check")
        batch.drop_constraint("ck_personal_accounts_source", type_="check")
        batch.drop_constraint(
            "fk_personal_accounts_group_id_account_groups", type_="foreignkey"
        )
        batch.drop_column("quality_synced_at")
        batch.drop_column("mutual_contact_count")
        batch.drop_column("friend_count")
        batch.drop_column("group_count")
        batch.drop_column("has_avatar")
        batch.drop_column("group_id")
        batch.drop_column("metadata_sync_status")
        batch.drop_column("validation_status")
        batch.drop_column("import_format")
        batch.drop_column("source_ref_id")
        batch.drop_column("source_ref_type")
        batch.drop_column("source")
    op.drop_table("account_groups")
