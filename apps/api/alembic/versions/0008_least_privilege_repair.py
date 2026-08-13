"""Restore least-privilege custom roles after the published 0006/0007 repair."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0008_least_privilege_repair"
down_revision: str | None = "0007_constraints_permissions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OPERATOR_ACTIONS = {
    "business.personal_accounts.manage",
    "promotion.templates.manage",
    "promotion.channels.manage",
    "promotion.domain.manage",
    "promotion.domain.purchase",
    "promotion.statistics.manage",
    "marketing.hyperlink_tasks.manage",
    "marketing.data_packages.manage",
    "marketing.hyperlink_templates.manage",
    "marketing.hyperlink_strategies.manage",
    "marketing.materials.manage",
    "marketing.direct_short_links.manage",
}


def _ancestor_ids(menus, menu_by_id: dict[int, object], menu_ids: set[int]) -> set[int]:
    result = set(menu_ids)
    for menu_id in list(menu_ids):
        current = menu_by_id.get(menu_id)
        while current is not None and current.parent_id is not None:
            result.add(current.parent_id)
            current = menu_by_id.get(current.parent_id)
    return result


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    required = {
        "user_groups",
        "system_menus",
        "role_menu_permissions",
        "role_action_permissions",
    }
    if not required <= tables:
        return

    roles = sa.Table("user_groups", sa.MetaData(), autoload_with=bind)
    menus = sa.Table("system_menus", sa.MetaData(), autoload_with=bind)
    role_menus = sa.Table("role_menu_permissions", sa.MetaData(), autoload_with=bind)
    role_actions = sa.Table("role_action_permissions", sa.MetaData(), autoload_with=bind)

    custom_role_ids = set(
        bind.execute(
            sa.select(roles.c.id).where(roles.c.system_key.is_(None))
        ).scalars()
    )
    if not custom_role_ids:
        return

    menu_rows = bind.execute(
        sa.select(menus.c.id, menus.c.parent_id, menus.c.public_id)
    ).all()
    menu_by_id = {row.id: row for row in menu_rows}
    operator_menu_ids = {
        row.id
        for row in menu_rows
        if row.public_id.startswith(
            ("menu_business", "menu_promotion", "menu_marketing")
        )
    }

    for role_id in custom_role_ids:
        current_actions = set(
            bind.execute(
                sa.select(role_actions.c.permission_key).where(
                    role_actions.c.role_id == role_id
                )
            ).scalars()
        )
        grants = bind.execute(
            sa.select(
                role_menus.c.id,
                role_menus.c.menu_id,
                role_menus.c.created_at,
            ).where(role_menus.c.role_id == role_id)
        ).all()
        current_menu_ids = {grant.menu_id for grant in grants}

        # 0006/0007's accidental signature is the complete operator menu and
        # action baseline. Its menu inserts share one database timestamp, so
        # remove that batch while preserving any earlier explicit grants.
        polluted = (
            OPERATOR_ACTIONS <= current_actions
            and operator_menu_ids <= current_menu_ids
        )
        repair_timestamp = None
        if polluted:
            operator_grants = [
                grant for grant in grants if grant.menu_id in operator_menu_ids
            ]
            timestamp_counts = Counter(grant.created_at for grant in operator_grants)
            if timestamp_counts:
                repair_timestamp, _ = timestamp_counts.most_common(1)[0]
                repair_ids = [
                    grant.id
                    for grant in operator_grants
                    if grant.created_at == repair_timestamp
                ]
                if repair_ids:
                    bind.execute(
                        role_menus.delete().where(role_menus.c.id.in_(repair_ids))
                    )

        # Only revoke operator actions that match the same database-timestamp
        # batch as the accidental menu baseline. Custom roles configured after
        # the published migration are left untouched.
        if polluted and repair_timestamp is not None:
            bind.execute(
                role_actions.delete().where(
                    role_actions.c.role_id == role_id,
                    role_actions.c.permission_key.in_(OPERATOR_ACTIONS),
                    role_actions.c.created_at == repair_timestamp,
                )
            )

        remaining_ids = set(
            bind.execute(
                sa.select(role_menus.c.menu_id).where(
                    role_menus.c.role_id == role_id
                )
            ).scalars()
        )
        for ancestor_id in _ancestor_ids(menus, menu_by_id, remaining_ids) - remaining_ids:
            bind.execute(
                role_menus.insert().values(role_id=role_id, menu_id=ancestor_id)
            )


def downgrade() -> None:
    # Restoring accidentally broadened privileges would be unsafe.
    pass
