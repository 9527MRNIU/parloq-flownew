"""rename material and trend navigation labels

Revision ID: 0072_menu_label_updates
Revises: 0071_pairing_failure_diagnosis
Create Date: 2026-08-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0072_menu_label_updates"
down_revision = "0071_pairing_failure_diagnosis"
branch_labels = None
depends_on = None


def _menus() -> sa.Table:
    return sa.table(
        "system_menus",
        sa.column("public_id", sa.String()),
        sa.column("name", sa.String()),
    )


def upgrade() -> None:
    menus = _menus()
    bind = op.get_bind()
    bind.execute(
        menus.update()
        .where(menus.c.public_id == "menu_promotion_trends")
        .values(name="趋势图表")
    )
    bind.execute(
        menus.update()
        .where(menus.c.public_id == "menu_resources_materials")
        .values(name="素材中心")
    )


def downgrade() -> None:
    menus = _menus()
    bind = op.get_bind()
    bind.execute(
        menus.update()
        .where(menus.c.public_id == "menu_promotion_trends")
        .values(name="趋势图")
    )
    bind.execute(
        menus.update()
        .where(menus.c.public_id == "menu_resources_materials")
        .values(name="素材库")
    )
