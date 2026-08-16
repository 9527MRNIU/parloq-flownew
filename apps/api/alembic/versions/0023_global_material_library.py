"""promote hyperlink materials to the tenant-wide resource library

Revision ID: 0023_global_material_library
Revises: 0022_account_reference_ids
Create Date: 2026-08-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0023_global_material_library"
down_revision = "0022_account_reference_ids"
branch_labels = None
depends_on = None


OLD_ACTION = "marketing.materials.manage"
NEW_ACTION = "resources.materials.manage"


def _replace_action_permission(bind, permissions, old: str, new: str) -> None:
    role_ids = bind.execute(
        sa.select(permissions.c.role_id).where(permissions.c.permission_key == old)
    ).scalars().all()
    for role_id in role_ids:
        new_exists = bind.execute(
            sa.select(permissions.c.id).where(
                permissions.c.role_id == role_id,
                permissions.c.permission_key == new,
            )
        ).scalar_one_or_none()
        if new_exists is None:
            bind.execute(
                permissions.update()
                .where(
                    permissions.c.role_id == role_id,
                    permissions.c.permission_key == old,
                )
                .values(permission_key=new)
            )
        else:
            bind.execute(
                permissions.delete().where(
                    permissions.c.role_id == role_id,
                    permissions.c.permission_key == old,
                )
            )


def _move_menu(
    bind,
    menus,
    *,
    public_id: str,
    parent_public_id: str,
    route_path: str,
    permission_key: str,
    sort_order: int,
) -> None:
    parent_id = bind.execute(
        sa.select(menus.c.id).where(menus.c.public_id == parent_public_id)
    ).scalar_one()
    bind.execute(
        menus.update()
        .where(
            menus.c.public_id.in_(
                ("menu_marketing_materials", "menu_resources_materials")
            )
        )
        .values(
            public_id=public_id,
            parent_id=parent_id,
            name="素材库",
            route_path=route_path,
            permission_key=permission_key,
            sort_order=sort_order,
            enabled=True,
            visible=True,
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    menus = sa.Table("system_menus", metadata, autoload_with=bind)
    action_permissions = sa.Table(
        "role_action_permissions", metadata, autoload_with=bind
    )

    op.rename_table("hyperlink_materials", "materials")
    _move_menu(
        bind,
        menus,
        public_id="menu_resources_materials",
        parent_public_id="menu_resources",
        route_path="/resources/materials",
        permission_key="resources.materials.read",
        sort_order=315,
    )
    _replace_action_permission(bind, action_permissions, OLD_ACTION, NEW_ACTION)


def downgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    menus = sa.Table("system_menus", metadata, autoload_with=bind)
    action_permissions = sa.Table(
        "role_action_permissions", metadata, autoload_with=bind
    )

    _replace_action_permission(bind, action_permissions, NEW_ACTION, OLD_ACTION)
    _move_menu(
        bind,
        menus,
        public_id="menu_marketing_materials",
        parent_public_id="menu_marketing_hyperlink",
        route_path="/hyperlink/materials",
        permission_key="marketing.materials.read",
        sort_order=215,
    )
    op.rename_table("materials", "hyperlink_materials")
