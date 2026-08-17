"""allow purchase-ready registrar orders

Revision ID: 0041_domain_order_status
Revises: 0040_domain_onboarding
Create Date: 2026-08-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0041_domain_order_status"
down_revision = "0040_domain_onboarding"
branch_labels = None
depends_on = None


OLD_STATUS_CONDITION = (
    "status IN ('pending_payment', 'paid', 'provisioning', 'unknown', "
    "'completed', 'failed', 'cancelled')"
)
NEW_STATUS_CONDITION = (
    "status IN ('pending_payment', 'paid', 'purchase_ready', 'provisioning', "
    "'unknown', 'completed', 'failed', 'cancelled')"
)


def _replace_status_constraint(condition: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("domain_orders") as batch:
            batch.drop_constraint("ck_domain_orders_status", type_="check")
            batch.create_check_constraint("ck_domain_orders_status", condition)
        return

    op.drop_constraint("ck_domain_orders_status", "domain_orders", type_="check")
    op.create_check_constraint(
        "ck_domain_orders_status",
        "domain_orders",
        condition,
    )


def upgrade() -> None:
    _replace_status_constraint(NEW_STATUS_CONDITION)


def downgrade() -> None:
    domain_orders = sa.table(
        "domain_orders",
        sa.column("status", sa.String(length=24)),
    )
    op.execute(
        domain_orders.update()
        .where(domain_orders.c.status == "purchase_ready")
        .values(status="paid")
    )
    _replace_status_constraint(OLD_STATUS_CONDITION)
