"""rename the default Baileys protocol node

Revision ID: 0064_baileys_web_protocol_name
Revises: 0063_protocol_routing_navigation
Create Date: 2026-08-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0064_baileys_web_protocol_name"
down_revision = "0063_protocol_routing_navigation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    nodes = sa.Table(
        "protocol_nodes", sa.MetaData(), autoload_with=connection
    )
    old_nodes = connection.execute(
        sa.select(nodes.c.id, nodes.c.created_by).where(
            nodes.c.name == "Baileys 默认协议"
        )
    ).all()
    for node_id, owner_id in old_nodes:
        conflict = connection.execute(
            sa.select(nodes.c.id).where(
                nodes.c.created_by == owner_id,
                nodes.c.name == "Baileys Web协议",
            )
        ).first()
        next_name = (
            "Baileys Web协议"
            if conflict is None
            else "Baileys Web协议（默认）"
        )
        connection.execute(
            nodes.update().where(nodes.c.id == node_id).values(name=next_name)
        )


def downgrade() -> None:
    connection = op.get_bind()
    nodes = sa.Table(
        "protocol_nodes", sa.MetaData(), autoload_with=connection
    )
    renamed_nodes = connection.execute(
        sa.select(nodes.c.id, nodes.c.created_by, nodes.c.name).where(
            nodes.c.name.in_(("Baileys Web协议", "Baileys Web协议（默认）"))
        )
    ).all()
    for node_id, owner_id, _name in sorted(
        renamed_nodes,
        key=lambda row: row[2] != "Baileys Web协议（默认）",
    ):
        conflict = connection.execute(
            sa.select(nodes.c.id).where(
                nodes.c.created_by == owner_id,
                nodes.c.name == "Baileys 默认协议",
            )
        ).first()
        if conflict is None:
            connection.execute(
                nodes.update()
                .where(nodes.c.id == node_id)
                .values(name="Baileys 默认协议")
            )
