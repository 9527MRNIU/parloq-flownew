"""Initial authentication, Bitly direct links and Meta pixel schema."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32
    )
    return "scrypt$16384$8$1${}${}".format(
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "user_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("system_key", sa.String(32), unique=True),
        sa.Column("description", sa.Text()),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_timestamps(),
    )
    op.create_index("ix_user_groups_name", "user_groups", ["name"])
    op.create_index("ix_user_groups_system_key", "user_groups", ["system_key"])
    op.create_table(
        "user_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(80), nullable=False, unique=True),
        sa.Column("display_name", sa.String(120)),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("user_groups.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="operator"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index("ix_user_accounts_username", "user_accounts", ["username"])
    op.create_index("ix_user_accounts_group_id", "user_accounts", ["group_id"])
    op.create_index("ix_user_accounts_role", "user_accounts", ["role"])
    op.create_index("ix_user_accounts_is_active", "user_accounts", ["is_active"])
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(64), nullable=False, unique=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"])
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_table(
        "bitly_provider_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("token_ciphertext", sa.Text(), nullable=False),
        sa.Column("token_fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("token_last4", sa.String(4), nullable=False, server_default=""),
        sa.Column("group_guid", sa.String(80), nullable=False),
        sa.Column("short_domain", sa.String(255), nullable=False, server_default="bit.ly"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("is_mock", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index("ix_bitly_provider_accounts_public_id", "bitly_provider_accounts", ["public_id"])
    op.create_index("ix_bitly_provider_accounts_enabled", "bitly_provider_accounts", ["enabled"])
    op.create_table(
        "direct_short_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(64), nullable=False, unique=True),
        sa.Column("title", sa.String(255)),
        sa.Column("target_url", sa.Text(), nullable=False),
        sa.Column("bitlink_id", sa.String(255), nullable=False, unique=True),
        sa.Column("short_url", sa.Text(), nullable=False),
        sa.Column("provider_account_id", sa.Integer(), sa.ForeignKey("bitly_provider_accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("last_error", sa.Text()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="RESTRICT"), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_direct_short_links_public_id", "direct_short_links", ["public_id"])
    op.create_index("ix_direct_short_links_bitlink_id", "direct_short_links", ["bitlink_id"])
    op.create_index("ix_direct_short_links_provider_account_id", "direct_short_links", ["provider_account_id"])
    op.create_index("ix_direct_short_links_status_created", "direct_short_links", ["status", "created_at"])
    op.create_table(
        "meta_pixels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("dataset_id", sa.String(120), nullable=False, unique=True),
        sa.Column("capi_token_ciphertext", sa.Text()),
        sa.Column("capi_token_last4", sa.String(4), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index("ix_meta_pixels_public_id", "meta_pixels", ["public_id"])
    op.create_index("ix_meta_pixels_dataset_id", "meta_pixels", ["dataset_id"])

    bind = op.get_bind()
    username = os.getenv("SEED_ADMIN_USERNAME", "admin")
    password = os.getenv("SEED_ADMIN_PASSWORD", "admin")
    group_id = bind.execute(
        sa.text(
            "INSERT INTO user_groups (name, system_key, description, is_builtin) "
            "VALUES (:name, 'admin', :description, true) RETURNING id"
        ),
        {"name": "管理员", "description": "系统内置管理员组"},
    ).scalar_one()
    bind.execute(
        sa.text(
            "INSERT INTO user_accounts "
            "(username, display_name, group_id, password_hash, role, is_active) "
            "VALUES (:username, 'Administrator', :group_id, :password_hash, 'admin', true)"
        ),
        {"username": username, "group_id": group_id, "password_hash": _password_hash(password)},
    )


def downgrade() -> None:
    op.drop_table("meta_pixels")
    op.drop_table("direct_short_links")
    op.drop_table("bitly_provider_accounts")
    op.drop_table("auth_sessions")
    op.drop_table("user_accounts")
    op.drop_table("user_groups")
