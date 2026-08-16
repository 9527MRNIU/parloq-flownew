"""add channel marketing configuration and Meta delivery ledger

Revision ID: 0032_channel_meta_delivery
Revises: 0031_protocol_routing
Create Date: 2026-08-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0032_channel_meta_delivery"
down_revision = "0031_protocol_routing"
branch_labels = None
depends_on = None


DEFAULT_META_EVENT_MAPPING = {
    "page_view": "PageView",
    "phone_submit": "Lead",
    "pairing_started": "InitiateCheckout",
    "pairing_verified": "CompleteRegistration",
}


def upgrade() -> None:
    connection = op.get_bind()
    sqlite = connection.dialect.name == "sqlite"
    recreate_mode = "never" if sqlite else "auto"

    with op.batch_alter_table("personal_accounts", recreate=recreate_mode) as batch:
        batch.add_column(
            sa.Column(
                "marketing_eligible",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
        batch.create_index(
            "ix_personal_accounts_marketing_eligible", ["marketing_eligible"]
        )

    with op.batch_alter_table("promotion_channels", recreate=recreate_mode) as batch:
        batch.add_column(
            sa.Column(
                "meta_browser_pixel_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
        batch.add_column(
            sa.Column(
                "meta_capi_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column(
                "meta_event_mapping_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch.add_column(
            sa.Column(
                "in_app_browser_mode",
                sa.String(24),
                nullable=False,
                server_default="allow",
            )
        )
        batch.add_column(
            sa.Column(
                "new_account_marketing_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
        if not sqlite:
            batch.create_check_constraint(
                "ck_promotion_channels_in_app_browser_mode",
                "in_app_browser_mode IN ('allow', 'guide_external')",
            )

    channels = sa.table(
        "promotion_channels",
        sa.column("pixel_id", sa.BigInteger()),
        sa.column("meta_browser_pixel_enabled", sa.Boolean()),
        sa.column("meta_event_mapping_json", sa.JSON()),
    )
    connection.execute(
        sa.update(channels).values(
            meta_event_mapping_json=DEFAULT_META_EVENT_MAPPING
        )
    )
    connection.execute(
        sa.update(channels)
        .where(channels.c.pixel_id.is_(None))
        .values(meta_browser_pixel_enabled=False)
    )

    op.create_table(
        "meta_conversion_deliveries",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("pixel_id", sa.BigInteger(), nullable=False),
        sa.Column("promotion_event_id", sa.BigInteger()),
        sa.Column("event_name", sa.String(64), nullable=False),
        sa.Column("event_id", sa.String(160), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("action_source", sa.String(32), nullable=False, server_default="website"),
        sa.Column("event_source_url", sa.Text()),
        sa.Column("user_data_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("custom_data_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("provider_trace_id", sa.String(255)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('pending', 'sending', 'retry', 'delivered', 'failed', 'skipped')",
            name="ck_meta_conversion_deliveries_status",
        ),
        sa.ForeignKeyConstraint(["channel_id"], ["promotion_channels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pixel_id"], ["meta_pixels.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["promotion_event_id"], ["promotion_events.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("pixel_id", "event_id", name="uq_meta_conversion_pixel_event"),
    )
    op.create_index("ix_meta_conversion_deliveries_public_id", "meta_conversion_deliveries", ["public_id"])
    op.create_index("ix_meta_conversion_deliveries_channel_id", "meta_conversion_deliveries", ["channel_id"])
    op.create_index("ix_meta_conversion_deliveries_pixel_id", "meta_conversion_deliveries", ["pixel_id"])
    op.create_index("ix_meta_conversion_deliveries_promotion_event_id", "meta_conversion_deliveries", ["promotion_event_id"])
    op.create_index("ix_meta_conversion_deliveries_event_name", "meta_conversion_deliveries", ["event_name"])
    op.create_index("ix_meta_conversion_deliveries_event_time", "meta_conversion_deliveries", ["event_time"])
    op.create_index("ix_meta_conversion_deliveries_status", "meta_conversion_deliveries", ["status"])
    op.create_index("ix_meta_conversion_deliveries_next_attempt_at", "meta_conversion_deliveries", ["next_attempt_at"])
    op.create_index("ix_meta_conversion_deliveries_due", "meta_conversion_deliveries", ["status", "next_attempt_at"])
    op.create_index("ix_meta_conversion_deliveries_channel_created", "meta_conversion_deliveries", ["channel_id", "created_at"])


def downgrade() -> None:
    op.drop_table("meta_conversion_deliveries")
    connection = op.get_bind()
    sqlite = connection.dialect.name == "sqlite"
    recreate_mode = "never" if sqlite else "auto"
    with op.batch_alter_table("promotion_channels", recreate=recreate_mode) as batch:
        if not sqlite:
            batch.drop_constraint("ck_promotion_channels_in_app_browser_mode", type_="check")
        batch.drop_column("new_account_marketing_enabled")
        batch.drop_column("in_app_browser_mode")
        batch.drop_column("meta_event_mapping_json")
        batch.drop_column("meta_capi_enabled")
        batch.drop_column("meta_browser_pixel_enabled")
    with op.batch_alter_table("personal_accounts", recreate=recreate_mode) as batch:
        batch.drop_index("ix_personal_accounts_marketing_eligible")
        batch.drop_column("marketing_eligible")
