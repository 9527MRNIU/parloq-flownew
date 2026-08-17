"""update public pairing rate-limit defaults

Revision ID: 0037_pairing_rate_defaults
Revises: 0036_sticky_delivery_repair
Create Date: 2026-08-17
"""

from __future__ import annotations

from copy import deepcopy

import sqlalchemy as sa
from alembic import op


revision = "0037_pairing_rate_defaults"
down_revision = "0036_sticky_delivery_repair"
branch_labels = None
depends_on = None


RULE_CHANGES = (
    (
        "ipStart",
        "ip_start",
        {"maxRequests": 20, "windowSeconds": 600},
        {"maxRequests": 5, "windowSeconds": 600},
    ),
    (
        "phoneAttempt",
        "phone_attempt",
        {"maxRequests": 3, "windowSeconds": 600},
        {"maxRequests": 5, "windowSeconds": 600},
    ),
    (
        "cancel",
        "cancel",
        {"maxRequests": 10, "windowSeconds": 60},
        {"maxRequests": 5, "windowSeconds": 600},
    ),
    (
        "channelAttempt",
        "channel_attempt",
        {"maxRequests": 100, "windowSeconds": 60},
        {"maxRequests": None, "windowSeconds": 60},
    ),
)


def _updated_policy(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    policy = deepcopy(value)
    changed = False
    for camel_key, snake_key, old_default, new_default in RULE_CHANGES:
        stored_key = (
            camel_key
            if camel_key in policy
            else snake_key if snake_key in policy else None
        )
        if stored_key is not None and policy[stored_key] == old_default:
            policy[stored_key] = dict(new_default)
            changed = True
    return policy if changed else None


def upgrade() -> None:
    connection = op.get_bind()
    protocols = sa.Table(
        "protocol_nodes",
        sa.MetaData(),
        autoload_with=connection,
    )
    for row in connection.execute(
        sa.select(protocols.c.id, protocols.c.rate_limit_policy_json)
    ).mappings():
        updated = _updated_policy(row["rate_limit_policy_json"])
        if updated is not None:
            connection.execute(
                protocols.update()
                .where(protocols.c.id == row["id"])
                .values(rate_limit_policy_json=updated)
            )


def downgrade() -> None:
    # Existing protocol-node policies are operator configuration. Reverting
    # values here could overwrite a deliberate setting made after this upgrade.
    pass
