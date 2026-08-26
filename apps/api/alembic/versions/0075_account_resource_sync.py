"""add account resource synchronization model

Revision ID: 0075_account_resource_sync
Revises: 0074_marketing_navigation
Create Date: 2026-08-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0075_account_resource_sync"
down_revision = "0074_marketing_navigation"
branch_labels = None
depends_on = None


POLICY_TABLES = (
    "protocol_nodes",
    "account_pairing_attempts",
    "account_metadata_sync_jobs",
)


def _normalized_policy(value: object) -> dict[str, bool]:
    source = value if isinstance(value, dict) else {}

    def boolean(key: str, default: bool) -> bool:
        raw = source.get(key)
        return raw if isinstance(raw, bool) else default

    group_details = source.get("groupDetails")
    if not isinstance(group_details, bool):
        group_details = False
    legacy_summary = source.get("groupSummary")
    if isinstance(legacy_summary, bool):
        group_details = group_details or legacy_summary
    elif "groupDetails" not in source:
        group_details = True

    return {
        "closeOnline": boolean("closeOnline", True),
        "avatar": boolean("avatar", True),
        "groupDetails": group_details,
        "contacts": boolean("contacts", True),
    }


def _rewrite_policies(transform) -> None:
    connection = op.get_bind()
    for table_name in POLICY_TABLES:
        table = sa.table(
            table_name,
            sa.column("id", sa.BigInteger()),
            sa.column("sync_policy_json", sa.JSON()),
        )
        rows = connection.execute(
            sa.select(table.c.id, table.c.sync_policy_json)
        ).mappings()
        for row in rows:
            updated = transform(row["sync_policy_json"])
            connection.execute(
                table.update()
                .where(table.c.id == row["id"])
                .values(sync_policy_json=updated)
            )


def upgrade() -> None:
    with op.batch_alter_table("personal_accounts") as batch:
        batch.add_column(sa.Column("unique_group_member_count", sa.Integer()))
        batch.add_column(sa.Column("wa_platform_raw", sa.String(length=32)))
        batch.add_column(
            sa.Column(
                "account_type",
                sa.String(length=16),
                nullable=False,
                server_default="unknown",
            )
        )
        batch.add_column(
            sa.Column(
                "device_os",
                sa.String(length=16),
                nullable=False,
                server_default="unknown",
            )
        )
        batch.add_column(
            sa.Column(
                "resource_sync_state_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch.create_check_constraint(
            "ck_personal_accounts_account_type",
            "account_type IN ('personal', 'business', 'unknown')",
        )
        batch.create_check_constraint(
            "ck_personal_accounts_device_os",
            "device_os IN ('android', 'ios', 'other', 'unknown')",
        )
        batch.create_index("ix_personal_accounts_account_type", ["account_type"])
        batch.create_index("ix_personal_accounts_device_os", ["device_os"])

    op.create_table(
        "account_contacts",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("contact_id", sa.String(length=191), nullable=False),
        sa.Column("jid", sa.String(length=191)),
        sa.Column("lid", sa.String(length=191)),
        sa.Column("phone_e164", sa.String(length=20)),
        sa.Column("saved_name", sa.String(length=255)),
        sa.Column("notify_name", sa.String(length=255)),
        sa.Column("verified_name", sa.String(length=255)),
        sa.Column("image_state", sa.String(length=255)),
        sa.Column("profile_status", sa.String(length=512)),
        sa.Column("source_mask", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "is_saved_contact", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "has_chat_history", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("last_interaction_at", sa.DateTime(timezone=True)),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["personal_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "contact_id", name="uq_account_contacts_account_contact"
        ),
    )
    op.create_index("ix_account_contacts_account_id", "account_contacts", ["account_id"])
    op.create_index("ix_account_contacts_active", "account_contacts", ["active"])
    op.create_index(
        "ix_account_contacts_last_interaction_at",
        "account_contacts",
        ["last_interaction_at"],
    )
    op.create_index("ix_account_contacts_synced_at", "account_contacts", ["synced_at"])
    op.create_index(
        "ix_account_contacts_account_active",
        "account_contacts",
        ["account_id", "active"],
    )
    op.create_index(
        "ix_account_contacts_account_phone",
        "account_contacts",
        ["account_id", "phone_e164"],
    )

    op.create_table(
        "account_whatsapp_groups",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("group_jid", sa.String(length=191), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("announce", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("restrict", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "community_type", sa.String(length=32), nullable=False, server_default="group"
        ),
        sa.Column("addressing_mode", sa.String(length=32)),
        sa.Column("linked_parent_jid", sa.String(length=191)),
        sa.Column("own_role", sa.String(length=24), nullable=False, server_default="member"),
        sa.Column("can_send", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["personal_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            "group_jid",
            name="uq_account_whatsapp_groups_account_group",
        ),
    )
    op.create_index(
        "ix_account_whatsapp_groups_account_id",
        "account_whatsapp_groups",
        ["account_id"],
    )
    op.create_index(
        "ix_account_whatsapp_groups_active", "account_whatsapp_groups", ["active"]
    )
    op.create_index(
        "ix_account_whatsapp_groups_synced_at",
        "account_whatsapp_groups",
        ["synced_at"],
    )
    op.create_index(
        "ix_account_whatsapp_groups_account_active",
        "account_whatsapp_groups",
        ["account_id", "active"],
    )

    _rewrite_policies(_normalized_policy)


def downgrade() -> None:
    op.drop_index(
        "ix_account_whatsapp_groups_account_active",
        table_name="account_whatsapp_groups",
    )
    op.drop_index(
        "ix_account_whatsapp_groups_synced_at", table_name="account_whatsapp_groups"
    )
    op.drop_index(
        "ix_account_whatsapp_groups_active", table_name="account_whatsapp_groups"
    )
    op.drop_index(
        "ix_account_whatsapp_groups_account_id", table_name="account_whatsapp_groups"
    )
    op.drop_table("account_whatsapp_groups")

    op.drop_index("ix_account_contacts_account_phone", table_name="account_contacts")
    op.drop_index("ix_account_contacts_account_active", table_name="account_contacts")
    op.drop_index("ix_account_contacts_synced_at", table_name="account_contacts")
    op.drop_index(
        "ix_account_contacts_last_interaction_at", table_name="account_contacts"
    )
    op.drop_index("ix_account_contacts_active", table_name="account_contacts")
    op.drop_index("ix_account_contacts_account_id", table_name="account_contacts")
    op.drop_table("account_contacts")

    with op.batch_alter_table("personal_accounts") as batch:
        batch.drop_index("ix_personal_accounts_device_os")
        batch.drop_index("ix_personal_accounts_account_type")
        batch.drop_constraint("ck_personal_accounts_device_os", type_="check")
        batch.drop_constraint("ck_personal_accounts_account_type", type_="check")
        batch.drop_column("resource_sync_state_json")
        batch.drop_column("device_os")
        batch.drop_column("account_type")
        batch.drop_column("wa_platform_raw")
        batch.drop_column("unique_group_member_count")

    def legacy_policy(value: object) -> dict[str, bool]:
        current = value if isinstance(value, dict) else {}
        group_details = bool(current.get("groupDetails"))
        return {
            "closeOnline": bool(current.get("closeOnline", True)),
            "avatar": bool(current.get("avatar", True)),
            "groupSummary": group_details,
            "groupDetails": group_details,
            "contacts": bool(current.get("contacts", False)),
            "chats": False,
            "messageHistory": False,
        }

    _rewrite_policies(legacy_policy)
