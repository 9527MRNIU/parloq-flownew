"""add automatic protocol build pipeline

Revision ID: 0067_protocol_build_pipeline
Revises: 0066_protocol_center_navigation
Create Date: 2026-08-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0067_protocol_build_pipeline"
down_revision = "0066_protocol_center_navigation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "protocol_definitions", sa.Column("artifact_digest", sa.String(64))
    )
    op.add_column(
        "protocol_definitions", sa.Column("artifact_integrity", sa.String(255))
    )
    op.add_column(
        "protocol_definitions", sa.Column("build_error_code", sa.String(64))
    )
    op.add_column(
        "protocol_definitions", sa.Column("build_error_message", sa.String(1024))
    )
    op.add_column(
        "protocol_definitions", sa.Column("build_started_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "protocol_definitions", sa.Column("built_at", sa.DateTime(timezone=True))
    )
    op.create_index(
        "ix_protocol_definitions_artifact_digest",
        "protocol_definitions",
        ["artifact_digest"],
    )
    op.create_table(
        "protocol_build_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("public_id", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "protocol_definition_id",
            sa.BigInteger(),
            sa.ForeignKey("protocol_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.String(1024)),
        sa.Column("log_excerpt", sa.Text()),
        sa.Column("artifact_digest", sa.String(64)),
        sa.Column("artifact_integrity", sa.String(255)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
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
            "status IN ('queued', 'building', 'succeeded', 'failed', 'requires_adaptation')",
            name="ck_protocol_build_jobs_status",
        ),
    )
    op.create_index(
        "ix_protocol_build_jobs_public_id",
        "protocol_build_jobs",
        ["public_id"],
        unique=True,
    )
    op.create_index(
        "ix_protocol_build_jobs_protocol_definition_id",
        "protocol_build_jobs",
        ["protocol_definition_id"],
    )
    op.create_index(
        "ix_protocol_build_jobs_status",
        "protocol_build_jobs",
        ["status"],
    )
    op.create_index(
        "ix_protocol_build_jobs_definition_status",
        "protocol_build_jobs",
        ["protocol_definition_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("protocol_build_jobs")
    op.drop_index(
        "ix_protocol_definitions_artifact_digest",
        table_name="protocol_definitions",
    )
    for column in (
        "built_at",
        "build_started_at",
        "build_error_message",
        "build_error_code",
        "artifact_integrity",
        "artifact_digest",
    ):
        op.drop_column("protocol_definitions", column)
