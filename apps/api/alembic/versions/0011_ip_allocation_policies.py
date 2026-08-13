"""Add configurable per-owner IP allocation policies."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0011_ip_allocation_policies"
down_revision: str | None = "0010_unified_account_pool"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ip_allocation_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "allocation_mode",
            sa.String(24),
            nullable=False,
            server_default="least_load",
        ),
        sa.Column(
            "country_match",
            sa.String(16),
            nullable=False,
            server_default="prefer",
        ),
        sa.Column(
            "max_accounts_per_ip",
            sa.Integer(),
            nullable=False,
            server_default="100",
        ),
        sa.Column("avoid_unhealthy", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sticky_binding", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "allocation_mode IN ('strict_one_to_one', 'tenant_reuse', 'least_load', 'manual')",
            name="ck_ip_allocation_policies_mode",
        ),
        sa.CheckConstraint(
            "country_match IN ('strict', 'prefer', 'off')",
            name="ck_ip_allocation_policies_country_match",
        ),
        sa.CheckConstraint(
            "max_accounts_per_ip >= 1 AND max_accounts_per_ip <= 10000",
            name="ck_ip_allocation_policies_max_accounts",
        ),
    )
    for column in ("public_id", "allocation_mode", "country_match", "created_by"):
        op.create_index(
            f"ix_ip_allocation_policies_{column}", "ip_allocation_policies", [column]
        )


def downgrade() -> None:
    op.drop_table("ip_allocation_policies")
