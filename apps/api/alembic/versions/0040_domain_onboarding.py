"""add lightweight domain onboarding state

Revision ID: 0040_domain_onboarding
Revises: 0039_platform_configuration
Create Date: 2026-08-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0040_domain_onboarding"
down_revision = "0039_platform_configuration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("domains") as batch:
        batch.add_column(
            sa.Column(
                "onboarding_status",
                sa.String(length=16),
                server_default="idle",
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column(
                "onboarding_stage",
                sa.String(length=32),
                server_default="not_started",
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column(
                "onboarding_state_json",
                sa.JSON(),
                server_default=sa.text("'{}'"),
                nullable=False,
            )
        )
        batch.add_column(sa.Column("onboarding_message", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("onboarding_attempted_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.create_check_constraint(
            "ck_domains_onboarding_status",
            "onboarding_status IN ('idle', 'running', 'waiting', 'failed', 'completed')",
        )
        batch.create_check_constraint(
            "ck_domains_onboarding_stage",
            "onboarding_stage IN ('not_started', 'cloudflare_zone', 'registrar_nameservers', 'cloudflare_dns', 'baota_site', 'public_verification', 'completed')",
        )
    op.create_index(
        "ix_domains_onboarding_status", "domains", ["onboarding_status"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_domains_onboarding_status", table_name="domains")
    with op.batch_alter_table("domains") as batch:
        batch.drop_constraint("ck_domains_onboarding_stage", type_="check")
        batch.drop_constraint("ck_domains_onboarding_status", type_="check")
        batch.drop_column("onboarding_completed_at")
        batch.drop_column("onboarding_attempted_at")
        batch.drop_column("onboarding_message")
        batch.drop_column("onboarding_state_json")
        batch.drop_column("onboarding_stage")
        batch.drop_column("onboarding_status")
