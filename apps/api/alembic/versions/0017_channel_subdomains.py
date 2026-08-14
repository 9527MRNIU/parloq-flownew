"""Add optional channel subdomain prefixes."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0017_channel_subdomains"
down_revision: str | None = "0016_promotion_template_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OLD_CONSTRAINT = "uq_promotion_channel_domain_slug"
NEW_CONSTRAINT = "uq_promotion_channel_domain_subdomain_slug"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        naming = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
        with op.batch_alter_table(
            "promotion_channels",
            recreate="always",
            naming_convention=naming,
        ) as batch:
            batch.add_column(
                sa.Column(
                    "subdomain_prefix",
                    sa.String(63),
                    nullable=False,
                    server_default="",
                )
            )
            batch.drop_constraint(OLD_CONSTRAINT, type_="unique")
            batch.create_unique_constraint(
                NEW_CONSTRAINT, ["domain_id", "subdomain_prefix", "slug"]
            )
            batch.create_index(
                "ix_promotion_channels_subdomain_prefix",
                ["subdomain_prefix"],
                unique=False,
            )
        return

    op.add_column(
        "promotion_channels",
        sa.Column(
            "subdomain_prefix", sa.String(63), nullable=False, server_default=""
        ),
    )
    op.drop_constraint(OLD_CONSTRAINT, "promotion_channels", type_="unique")
    op.create_unique_constraint(
        NEW_CONSTRAINT,
        "promotion_channels",
        ["domain_id", "subdomain_prefix", "slug"],
    )
    op.create_index(
        "ix_promotion_channels_subdomain_prefix",
        "promotion_channels",
        ["subdomain_prefix"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        naming = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
        with op.batch_alter_table(
            "promotion_channels",
            recreate="always",
            naming_convention=naming,
        ) as batch:
            batch.drop_index("ix_promotion_channels_subdomain_prefix")
            batch.drop_constraint(NEW_CONSTRAINT, type_="unique")
            batch.create_unique_constraint(
                OLD_CONSTRAINT, ["domain_id", "slug"]
            )
            batch.drop_column("subdomain_prefix")
        return

    op.drop_index(
        "ix_promotion_channels_subdomain_prefix",
        table_name="promotion_channels",
    )
    op.drop_constraint(NEW_CONSTRAINT, "promotion_channels", type_="unique")
    op.create_unique_constraint(
        OLD_CONSTRAINT, "promotion_channels", ["domain_id", "slug"]
    )
    op.drop_column("promotion_channels", "subdomain_prefix")
