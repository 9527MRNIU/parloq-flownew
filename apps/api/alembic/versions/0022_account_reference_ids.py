"""store account-domain references as Snowflake decimal strings

Revision ID: 0022_account_reference_ids
Revises: 0021_account_center_navigation
Create Date: 2026-08-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0022_account_reference_ids"
down_revision = "0021_account_center_navigation"
branch_labels = None
depends_on = None


def _tables(bind):
    metadata = sa.MetaData()
    return (
        sa.Table("personal_accounts", metadata, autoload_with=bind),
        sa.Table("promotion_channels", metadata, autoload_with=bind),
        sa.Table("hyperlink_tasks", metadata, autoload_with=bind),
    )


def _rewrite(*, to_snowflake: bool) -> None:
    bind = op.get_bind()
    accounts, channels, tasks = _tables(bind)
    account_rows = bind.execute(
        sa.select(accounts.c.id, accounts.c.public_id)
    ).all()
    channel_rows = bind.execute(
        sa.select(channels.c.id, channels.c.public_id)
    ).all()
    account_map = {
        (public_id if to_snowflake else str(row_id)): (
            str(row_id) if to_snowflake else public_id
        )
        for row_id, public_id in account_rows
    }
    channel_map = {
        (public_id if to_snowflake else str(row_id)): (
            str(row_id) if to_snowflake else public_id
        )
        for row_id, public_id in channel_rows
    }

    for account_id, source_ref_id in bind.execute(
        sa.select(accounts.c.id, accounts.c.source_ref_id).where(
            accounts.c.source_ref_type.in_(
                ("promotion_channel", "promotion_channel_fission")
            ),
            accounts.c.source_ref_id.is_not(None),
        )
    ).all():
        replacement = channel_map.get(source_ref_id)
        if replacement is not None:
            bind.execute(
                accounts.update()
                .where(accounts.c.id == account_id)
                .values(source_ref_id=replacement)
            )

    for task_id, references in bind.execute(
        sa.select(tasks.c.id, tasks.c.account_public_ids)
    ).all():
        if not isinstance(references, list):
            continue
        rewritten = [account_map.get(str(value), str(value)) for value in references]
        if rewritten != references:
            bind.execute(
                tasks.update()
                .where(tasks.c.id == task_id)
                .values(account_public_ids=rewritten)
            )


def upgrade() -> None:
    _rewrite(to_snowflake=True)


def downgrade() -> None:
    _rewrite(to_snowflake=False)
