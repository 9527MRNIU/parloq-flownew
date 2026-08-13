"""Add IP proxy endpoints and account bindings."""

from __future__ import annotations

import base64
import hashlib
import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from cryptography.fernet import Fernet


revision: str = "0002_ip_proxy_management"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _encrypt_legacy_secret(value: str) -> str:
    secret = os.getenv("APP_SECRET_KEY", "parloq-dev-secret-change-me").encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return "v1:" + Fernet(key).encrypt(value.encode("utf-8")).decode("ascii")


def _create_proxy_table() -> None:
    op.create_table(
        "proxy_endpoints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("protocol", sa.String(16), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("username_ciphertext", sa.Text()),
        sa.Column("username_last4", sa.String(4), nullable=False, server_default=""),
        sa.Column("password_ciphertext", sa.Text()),
        sa.Column("password_last4", sa.String(4), nullable=False, server_default=""),
        sa.Column("country_code", sa.String(2)),
        sa.Column("provider", sa.String(120)),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("health_status", sa.String(16), nullable=False, server_default="untested"),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "protocol IN ('http', 'https', 'socks5')",
            name="ck_proxy_endpoints_protocol",
        ),
        sa.CheckConstraint(
            "health_status IN ('untested', 'healthy', 'unhealthy')",
            name="ck_proxy_endpoints_health_status",
        ),
        sa.CheckConstraint("port >= 1 AND port <= 65535", name="ck_proxy_endpoints_port"),
    )
    op.create_index("ix_proxy_endpoints_public_id", "proxy_endpoints", ["public_id"])
    op.create_index("ix_proxy_endpoints_name", "proxy_endpoints", ["name"])
    op.create_index("ix_proxy_endpoints_protocol", "proxy_endpoints", ["protocol"])
    op.create_index("ix_proxy_endpoints_host", "proxy_endpoints", ["host"])
    op.create_index("ix_proxy_endpoints_country_code", "proxy_endpoints", ["country_code"])
    op.create_index("ix_proxy_endpoints_provider", "proxy_endpoints", ["provider"])
    op.create_index("ix_proxy_endpoints_enabled", "proxy_endpoints", ["enabled"])
    op.create_index("ix_proxy_endpoints_health_status", "proxy_endpoints", ["health_status"])
    op.create_index("ix_proxy_endpoints_last_checked_at", "proxy_endpoints", ["last_checked_at"])
    op.create_index("ix_proxy_endpoints_archived_at", "proxy_endpoints", ["archived_at"])


def _upgrade_legacy_create_all_proxy_table(bind: sa.Connection) -> None:
    columns = {column["name"] for column in sa.inspect(bind).get_columns("proxy_endpoints")}
    if "username_ciphertext" not in columns:
        op.add_column("proxy_endpoints", sa.Column("username_ciphertext", sa.Text()))
    if "username_last4" not in columns:
        op.add_column(
            "proxy_endpoints",
            sa.Column("username_last4", sa.String(4), nullable=False, server_default=""),
        )
    if "username" in columns:
        rows = bind.execute(sa.text("SELECT id, username FROM proxy_endpoints")).mappings()
        for row in rows:
            username = str(row["username"] or "").strip()
            bind.execute(
                sa.text(
                    "UPDATE proxy_endpoints "
                    "SET username_ciphertext=:ciphertext, username_last4=:last4 WHERE id=:id"
                ),
                {
                    "id": row["id"],
                    "ciphertext": _encrypt_legacy_secret(username) if username else None,
                    "last4": username[-4:] if username else "",
                },
            )
        op.drop_column("proxy_endpoints", "username")


def _create_binding_table() -> None:
    op.create_table(
        "account_proxy_bindings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(64), nullable=False, unique=True),
        sa.Column("account_public_id", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "proxy_id",
            sa.Integer(),
            sa.ForeignKey("proxy_endpoints.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_account_proxy_bindings_public_id", "account_proxy_bindings", ["public_id"]
    )
    op.create_index(
        "ix_account_proxy_bindings_account_public_id",
        "account_proxy_bindings",
        ["account_public_id"],
    )
    op.create_index(
        "ix_account_proxy_bindings_proxy_id", "account_proxy_bindings", ["proxy_id"]
    )


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "proxy_endpoints" not in tables:
        _create_proxy_table()
    else:
        _upgrade_legacy_create_all_proxy_table(bind)
    if "account_proxy_bindings" not in tables:
        _create_binding_table()


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "account_proxy_bindings" in tables:
        op.drop_table("account_proxy_bindings")
    if "proxy_endpoints" in tables:
        op.drop_table("proxy_endpoints")
