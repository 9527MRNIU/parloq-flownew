"""Make strict promotion template protection the system default."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0018_strict_template_defaults"
down_revision: str | None = "0017_channel_subdomains"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _set_defaults(
    *, protection: str, action: str, lock_zoom: bool, signals: str
) -> None:
    with op.batch_alter_table("promotion_template_policies") as batch:
        batch.alter_column(
            "protection_mode",
            existing_type=sa.String(16),
            existing_nullable=False,
            server_default=protection,
        )
        batch.alter_column(
            "devtools_action",
            existing_type=sa.String(16),
            existing_nullable=False,
            server_default=action,
        )
        batch.alter_column(
            "lock_viewport_zoom",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=sa.true() if lock_zoom else sa.false(),
        )
        batch.alter_column(
            "device_signals",
            existing_type=sa.String(16),
            existing_nullable=False,
            server_default=signals,
        )


def upgrade() -> None:
    # Only change defaults for policies created from this release onward.
    # Existing tenant choices, including intentionally relaxed policies, stay
    # untouched.
    _set_defaults(
        protection="strict",
        action="blank",
        lock_zoom=True,
        signals="enhanced",
    )


def downgrade() -> None:
    _set_defaults(
        protection="basic",
        action="log",
        lock_zoom=False,
        signals="standard",
    )
