"""add durable hyperlink task submission phases and template snapshots

Revision ID: 0026_task_observability
Revises: 0025_text_material_roles
Create Date: 2026-08-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0026_task_observability"
down_revision = "0025_text_material_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("hyperlink_tasks") as batch:
        batch.add_column(sa.Column("template_name_snapshot", sa.String(120), nullable=True))
        batch.add_column(sa.Column("template_snapshot_json", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("submitting_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("accepted_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("submission_failed_count", sa.Integer(), nullable=False, server_default="0"))

    with op.batch_alter_table("hyperlink_task_deliveries") as batch:
        batch.add_column(sa.Column("submission_status", sa.String(16), nullable=False, server_default="pending"))
        batch.add_column(sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("submission_failed_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index("ix_hyperlink_task_deliveries_submission_status", ["submission_status"])
        batch.create_index("ix_hyperlink_task_deliveries_submitted_at", ["submitted_at"])

    # Historical rows used ``status=queued`` after the gateway had accepted
    # them, so a linked message row is the strongest available backfill signal.
    op.execute(sa.text("""
        UPDATE hyperlink_task_deliveries
        SET submission_status = CASE
          WHEN status = 'retry' THEN 'retry'
          WHEN status = 'sending' THEN 'retry'
          WHEN status = 'failed' THEN 'failed'
          WHEN message_delivery_id IS NOT NULL THEN 'accepted'
          ELSE 'pending'
        END
    """))
    op.execute(sa.text("""
        UPDATE hyperlink_task_deliveries
        SET submitted_at = updated_at
        WHERE submission_status = 'accepted' AND submitted_at IS NULL
    """))
    op.execute(sa.text("""
        UPDATE hyperlink_task_deliveries
        SET submission_failed_at = updated_at
        WHERE submission_status = 'failed' AND submission_failed_at IS NULL
    """))


def downgrade() -> None:
    with op.batch_alter_table("hyperlink_task_deliveries") as batch:
        batch.drop_index("ix_hyperlink_task_deliveries_submitted_at")
        batch.drop_index("ix_hyperlink_task_deliveries_submission_status")
        batch.drop_column("submission_failed_at")
        batch.drop_column("submitted_at")
        batch.drop_column("submission_status")
    with op.batch_alter_table("hyperlink_tasks") as batch:
        batch.drop_column("submission_failed_count")
        batch.drop_column("accepted_count")
        batch.drop_column("submitting_count")
        batch.drop_column("template_snapshot_json")
        batch.drop_column("template_name_snapshot")
