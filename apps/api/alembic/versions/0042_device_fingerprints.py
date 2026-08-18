"""add tenant-scoped promotion device fingerprints

Revision ID: 0042_device_fingerprints
Revises: 0041_domain_order_status
Create Date: 2026-08-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0042_device_fingerprints"
down_revision = "0041_domain_order_status"
branch_labels = None
depends_on = None


def _replace_device_signal_constraint(*, fingerprint: bool) -> None:
    allowed = (
        "device_signals IN ('off', 'standard', 'enhanced', 'fingerprint')"
        if fingerprint
        else "device_signals IN ('off', 'standard', 'enhanced')"
    )
    default = "fingerprint" if fingerprint else "enhanced"
    with op.batch_alter_table("promotion_template_policies") as batch:
        batch.drop_constraint(
            "ck_promotion_template_policy_device_signals",
            type_="check",
        )
        batch.create_check_constraint(
            "ck_promotion_template_policy_device_signals",
            allowed,
        )
        batch.alter_column(
            "device_signals",
            existing_type=sa.String(16),
            existing_nullable=False,
            server_default=default,
        )


def _add_fingerprint_columns(table: str) -> None:
    with op.batch_alter_table(table) as batch:
        batch.add_column(sa.Column("visitor_fingerprint_hash", sa.String(64)))
        batch.add_column(sa.Column("fingerprint_version", sa.String(40)))
        batch.add_column(sa.Column("fingerprint_quality", sa.String(16)))


def upgrade() -> None:
    _replace_device_signal_constraint(fingerprint=True)
    policies = sa.table(
        "promotion_template_policies",
        sa.column("device_signals", sa.String(16)),
    )
    # The new tier is the direct successor to the former strongest tier.
    # Explicitly relaxed standard/off policies remain untouched.
    op.execute(
        policies.update()
        .where(policies.c.device_signals == "enhanced")
        .values(device_signals="fingerprint")
    )
    _add_fingerprint_columns("promotion_events")
    _add_fingerprint_columns("account_pairing_attempts")
    op.create_index(
        "ix_promotion_events_channel_fingerprint",
        "promotion_events",
        ["channel_id", "visitor_fingerprint_hash"],
    )
    op.create_index(
        "ix_account_pairing_attempts_channel_fingerprint_created",
        "account_pairing_attempts",
        ["channel_id", "visitor_fingerprint_hash", "created_at"],
    )


def downgrade() -> None:
    policies = sa.table(
        "promotion_template_policies",
        sa.column("device_signals", sa.String(16)),
    )
    op.execute(
        policies.update()
        .where(policies.c.device_signals == "fingerprint")
        .values(device_signals="enhanced")
    )
    _replace_device_signal_constraint(fingerprint=False)
    op.drop_index(
        "ix_account_pairing_attempts_channel_fingerprint_created",
        table_name="account_pairing_attempts",
    )
    op.drop_index(
        "ix_promotion_events_channel_fingerprint",
        table_name="promotion_events",
    )
    with op.batch_alter_table("account_pairing_attempts") as batch:
        batch.drop_column("fingerprint_quality")
        batch.drop_column("fingerprint_version")
        batch.drop_column("visitor_fingerprint_hash")
    with op.batch_alter_table("promotion_events") as batch:
        batch.drop_column("fingerprint_quality")
        batch.drop_column("fingerprint_version")
        batch.drop_column("visitor_fingerprint_hash")
