"""add event-driven proxy health and cooldown

Revision ID: 0068_proxy_health_cooldown
Revises: 0067_protocol_build_pipeline
Create Date: 2026-08-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0068_proxy_health_cooldown"
down_revision = "0067_protocol_build_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("proxy_endpoints") as batch:
        batch.add_column(
            sa.Column(
                "consecutive_failures",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(sa.Column("cooldown_until", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("last_success_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("last_failure_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("last_check_source", sa.String(24)))
        batch.add_column(sa.Column("latency_ms", sa.Integer()))
        batch.create_check_constraint(
            "ck_proxy_endpoints_consecutive_failures",
            "consecutive_failures >= 0",
        )
        batch.create_check_constraint(
            "ck_proxy_endpoints_latency_ms",
            "latency_ms IS NULL OR latency_ms >= 0",
        )
        batch.create_index(
            "ix_proxy_endpoints_cooldown_until", ["cooldown_until"]
        )
        batch.create_index(
            "ix_proxy_endpoints_last_check_source", ["last_check_source"]
        )
        batch.create_index(
            "ix_proxy_endpoints_allocation_health",
            ["enabled", "health_status", "cooldown_until"],
        )

    with op.batch_alter_table("ip_allocation_policies") as batch:
        batch.drop_constraint(
            "ck_ip_allocation_policies_country_match", type_="check"
        )
        batch.alter_column(
            "country_match",
            existing_type=sa.String(16),
            type_=sa.String(24),
            existing_nullable=False,
        )
        batch.add_column(
            sa.Column(
                "failure_threshold", sa.Integer(), nullable=False, server_default="2"
            )
        )
        batch.add_column(
            sa.Column(
                "cooldown_seconds", sa.Integer(), nullable=False, server_default="900"
            )
        )
    # Existing installations matched the phone-derived country. Preserve that
    # behavior while new policies default to the visitor/access country.
    op.execute(
        "UPDATE ip_allocation_policies SET country_match='phone_country' "
        "WHERE country_match IN ('strict','prefer','off')"
    )
    with op.batch_alter_table("ip_allocation_policies") as batch:
        batch.alter_column(
            "country_match",
            existing_type=sa.String(24),
            existing_nullable=False,
            server_default="visitor_country",
        )
        batch.create_check_constraint(
            "ck_ip_allocation_policies_country_match",
            "country_match IN ('visitor_country', 'phone_country')",
        )
        batch.create_check_constraint(
            "ck_ip_allocation_policies_failure_threshold",
            "failure_threshold >= 1 AND failure_threshold <= 10",
        )
        batch.create_check_constraint(
            "ck_ip_allocation_policies_cooldown_seconds",
            "cooldown_seconds >= 60 AND cooldown_seconds <= 86400",
        )

    op.create_table(
        "proxy_health_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("public_id", sa.String(80), nullable=False),
        sa.Column(
            "proxy_id",
            sa.BigInteger(),
            sa.ForeignKey("proxy_endpoints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.BigInteger(),
            sa.ForeignKey("personal_accounts.id", ondelete="SET NULL"),
        ),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("reason_category", sa.String(64), nullable=False),
        sa.Column("proxy_fingerprint", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
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
            "outcome IN ('success', 'failure')",
            name="ck_proxy_health_events_outcome",
        ),
    )
    op.create_index(
        "ix_proxy_health_events_public_id",
        "proxy_health_events",
        ["public_id"],
        unique=True,
    )
    op.create_index(
        "ix_proxy_health_events_proxy_id", "proxy_health_events", ["proxy_id"]
    )
    op.create_index(
        "ix_proxy_health_events_account_id", "proxy_health_events", ["account_id"]
    )
    op.create_index(
        "ix_proxy_health_events_outcome", "proxy_health_events", ["outcome"]
    )
    op.create_index(
        "ix_proxy_health_events_occurred_at", "proxy_health_events", ["occurred_at"]
    )
    op.create_index(
        "ix_proxy_health_events_proxy_occurred",
        "proxy_health_events",
        ["proxy_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_table("proxy_health_events")
    with op.batch_alter_table("ip_allocation_policies") as batch:
        batch.drop_constraint(
            "ck_ip_allocation_policies_cooldown_seconds", type_="check"
        )
        batch.drop_constraint(
            "ck_ip_allocation_policies_failure_threshold", type_="check"
        )
        batch.drop_constraint(
            "ck_ip_allocation_policies_country_match", type_="check"
        )
    op.execute(
        "UPDATE ip_allocation_policies SET country_match='prefer' "
        "WHERE country_match IN ('visitor_country','phone_country')"
    )
    with op.batch_alter_table("ip_allocation_policies") as batch:
        batch.drop_column("cooldown_seconds")
        batch.drop_column("failure_threshold")
        batch.alter_column(
            "country_match",
            existing_type=sa.String(24),
            type_=sa.String(16),
            existing_nullable=False,
            server_default="prefer",
        )
        batch.create_check_constraint(
            "ck_ip_allocation_policies_country_match",
            "country_match IN ('strict', 'prefer', 'off')",
        )
    with op.batch_alter_table("proxy_endpoints") as batch:
        batch.drop_index("ix_proxy_endpoints_allocation_health")
        batch.drop_index("ix_proxy_endpoints_last_check_source")
        batch.drop_index("ix_proxy_endpoints_cooldown_until")
        batch.drop_constraint("ck_proxy_endpoints_latency_ms", type_="check")
        batch.drop_constraint(
            "ck_proxy_endpoints_consecutive_failures", type_="check"
        )
        for column in (
            "latency_ms",
            "last_check_source",
            "last_failure_at",
            "last_success_at",
            "cooldown_until",
            "consecutive_failures",
        ):
            batch.drop_column(column)
