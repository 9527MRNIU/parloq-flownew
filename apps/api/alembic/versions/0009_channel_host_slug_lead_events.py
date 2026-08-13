"""Scope channel slugs to domains and link submission events to leads."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0009_channel_host_slug_leads"
down_revision: str | None = "0008_least_privilege_repair"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    slug_constraints = [
        constraint
        for constraint in inspector.get_unique_constraints("promotion_channels")
        if tuple(constraint.get("column_names") or ()) == ("slug",)
    ]

    if bind.dialect.name == "sqlite":
        naming = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
        with op.batch_alter_table(
            "promotion_channels",
            recreate="always",
            naming_convention=naming,
        ) as batch:
            for constraint in slug_constraints:
                batch.drop_constraint(
                    constraint.get("name") or "uq_promotion_channels_slug",
                    type_="unique",
                )
            batch.create_unique_constraint(
                "uq_promotion_channel_domain_slug", ["domain_id", "slug"]
            )
        with op.batch_alter_table("promotion_events") as batch:
            batch.add_column(sa.Column("lead_id", sa.Integer()))
            batch.create_foreign_key(
                "fk_promotion_events_lead_id_promotion_leads",
                "promotion_leads",
                ["lead_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch.create_index(
                "ix_promotion_events_lead_id", ["lead_id"], unique=False
            )
    else:
        for constraint in slug_constraints:
            if constraint.get("name"):
                op.drop_constraint(
                    constraint["name"], "promotion_channels", type_="unique"
                )
        op.create_unique_constraint(
            "uq_promotion_channel_domain_slug",
            "promotion_channels",
            ["domain_id", "slug"],
        )
        op.add_column("promotion_events", sa.Column("lead_id", sa.Integer()))
        op.create_foreign_key(
            "fk_promotion_events_lead_id_promotion_leads",
            "promotion_events",
            "promotion_leads",
            ["lead_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(
            "ix_promotion_events_lead_id",
            "promotion_events",
            ["lead_id"],
            unique=False,
        )


def downgrade() -> None:
    # A global slug constraint cannot be restored after valid host-scoped
    # duplicates have been created, so this forward data-contract repair is
    # intentionally non-destructive.
    pass
