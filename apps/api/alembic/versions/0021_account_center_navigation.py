"""merge account import into management and reorder account center menus

Revision ID: 0021_account_center_navigation
Revises: 0020_account_pairing_attempts
Create Date: 2026-08-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0021_account_center_navigation"
down_revision = "0020_account_pairing_attempts"
branch_labels = None
depends_on = None


def _update_menu(bind, menus, public_id: str, **values) -> None:
    bind.execute(
        menus.update().where(menus.c.public_id == public_id).values(**values)
    )


def upgrade() -> None:
    bind = op.get_bind()
    menus = sa.Table("system_menus", sa.MetaData(), autoload_with=bind)

    for index, public_id in enumerate(
        (
            "menu_resources_accounts_import",
            "menu_resources_accounts_export",
            "menu_resources_accounts_manage",
            "menu_resources_accounts_groups",
            "menu_resources_accounts_statistics",
        ),
        start=1,
    ):
        _update_menu(bind, menus, public_id, sort_order=3000 + index)
    _update_menu(
        bind,
        menus,
        "menu_resources_accounts_import",
        enabled=False,
        visible=False,
        sort_order=319,
    )
    _update_menu(bind, menus, "menu_resources_accounts_statistics", sort_order=311)
    _update_menu(bind, menus, "menu_resources_accounts_groups", sort_order=312)
    _update_menu(bind, menus, "menu_resources_accounts_manage", sort_order=313)
    _update_menu(bind, menus, "menu_resources_accounts_export", sort_order=314)


def downgrade() -> None:
    bind = op.get_bind()
    menus = sa.Table("system_menus", sa.MetaData(), autoload_with=bind)

    for index, public_id in enumerate(
        (
            "menu_resources_accounts_import",
            "menu_resources_accounts_export",
            "menu_resources_accounts_manage",
            "menu_resources_accounts_groups",
            "menu_resources_accounts_statistics",
        ),
        start=1,
    ):
        _update_menu(bind, menus, public_id, sort_order=3000 + index)
    _update_menu(
        bind,
        menus,
        "menu_resources_accounts_import",
        enabled=True,
        visible=True,
        sort_order=311,
    )
    _update_menu(bind, menus, "menu_resources_accounts_export", sort_order=312)
    _update_menu(bind, menus, "menu_resources_accounts_manage", sort_order=313)
    _update_menu(bind, menus, "menu_resources_accounts_groups", sort_order=314)
    _update_menu(bind, menus, "menu_resources_accounts_statistics", sort_order=315)
