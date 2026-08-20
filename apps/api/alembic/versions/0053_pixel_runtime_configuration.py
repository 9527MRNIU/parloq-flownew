"""move Meta delivery configuration from channels to pixels

Revision ID: 0053_pixel_runtime_config
Revises: 0052_bitly_pool_analytics
Create Date: 2026-08-20
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op


revision = "0053_pixel_runtime_config"
down_revision = "0052_bitly_pool_analytics"
branch_labels = None
depends_on = None


DEFAULT_EVENT_MAPPING = {
    "page_view": "PageView",
    "phone_submit": "Lead",
    "pairing_started": "InitiateCheckout",
    "pairing_verified": "CompleteRegistration",
}


def _mapping(value: object) -> dict[str, str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = {}
    source = value if isinstance(value, dict) else {}
    return {
        key: str(source.get(key) or default)
        for key, default in DEFAULT_EVENT_MAPPING.items()
    }


def upgrade() -> None:
    op.add_column(
        "meta_pixels",
        sa.Column(
            "browser_pixel_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "meta_pixels",
        sa.Column(
            "capi_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "meta_pixels",
        sa.Column(
            "event_mapping_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )

    connection = op.get_bind()
    pixels = sa.table(
        "meta_pixels",
        sa.column("id", sa.BigInteger()),
        sa.column("capi_token_ciphertext", sa.Text()),
        sa.column("browser_pixel_enabled", sa.Boolean()),
        sa.column("capi_enabled", sa.Boolean()),
        sa.column("event_mapping_json", sa.JSON()),
    )
    channels = sa.table(
        "promotion_channels",
        sa.column("id", sa.BigInteger()),
        sa.column("pixel_id", sa.BigInteger()),
        sa.column("meta_browser_pixel_enabled", sa.Boolean()),
        sa.column("meta_capi_enabled", sa.Boolean()),
        sa.column("meta_event_mapping_json", sa.JSON()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    for pixel in connection.execute(
        sa.select(pixels.c.id, pixels.c.capi_token_ciphertext)
    ).mappings():
        bound_channels = list(
            connection.execute(
                sa.select(
                    channels.c.meta_browser_pixel_enabled,
                    channels.c.meta_capi_enabled,
                    channels.c.meta_event_mapping_json,
                )
                .where(channels.c.pixel_id == pixel["id"])
                .order_by(channels.c.updated_at.desc(), channels.c.id.desc())
            ).mappings()
        )
        if bound_channels:
            browser_enabled = any(
                bool(row["meta_browser_pixel_enabled"])
                for row in bound_channels
            )
            capi_enabled = bool(pixel["capi_token_ciphertext"]) and any(
                bool(row["meta_capi_enabled"]) for row in bound_channels
            )
            event_mapping = _mapping(
                bound_channels[0]["meta_event_mapping_json"]
            )
        else:
            browser_enabled = False
            capi_enabled = False
            event_mapping = DEFAULT_EVENT_MAPPING
        connection.execute(
            sa.update(pixels)
            .where(pixels.c.id == pixel["id"])
            .values(
                browser_pixel_enabled=browser_enabled,
                capi_enabled=capi_enabled,
                event_mapping_json=event_mapping,
            )
        )


def downgrade() -> None:
    op.drop_column("meta_pixels", "event_mapping_json")
    op.drop_column("meta_pixels", "capi_enabled")
    op.drop_column("meta_pixels", "browser_pixel_enabled")
