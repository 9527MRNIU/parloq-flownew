"""normalize legacy public template contract identifiers

Revision ID: 0033_white_label_templates
Revises: 0032_channel_meta_delivery
Create Date: 2026-08-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0033_white_label_templates"
down_revision = "0032_channel_meta_delivery"
branch_labels = None
depends_on = None


TEXT_REPLACEMENTS = (
    (b"parloq-promotion-config", b"promotion-runtime-config"),
    (b"window.parloqSubmitPhone", b"window.PromotionBridge.submitPhone"),
    (b"parloq_visitor_id", b"promotion_visitor_id"),
    (b"data-parloq-manual", b"data-promotion-manual"),
    (b"parloq:inspection-detected", b"promotion:inspection-detected"),
)


def _normalized_manifest(value: object) -> tuple[object, bool]:
    if not isinstance(value, dict):
        return value, False
    result = dict(value)
    changed = False
    if result.get("schema") == "parloq-promotion-template/v1":
        result["schema"] = "promotion-template/v1"
        changed = True
    if result.get("runtime") == "parloq-browser-bridge/v1":
        result["runtime"] = "promotion-browser-bridge/v1"
        changed = True
    return result, changed


def _normalized_text(value: bytes) -> tuple[bytes, bool]:
    result = value
    for source, target in TEXT_REPLACEMENTS:
        result = result.replace(source, target)
    return result, result != value


def upgrade() -> None:
    connection = op.get_bind()
    templates = sa.table(
        "promotion_templates",
        sa.column("id", sa.BigInteger()),
        sa.column("manifest_json", sa.JSON()),
        sa.column("index_html", sa.Text()),
    )
    assets = sa.table(
        "promotion_assets",
        sa.column("id", sa.BigInteger()),
        sa.column("content_type", sa.String()),
        sa.column("content", sa.LargeBinary()),
    )

    for row in connection.execute(
        sa.select(templates.c.id, templates.c.manifest_json, templates.c.index_html)
    ).mappings():
        manifest, manifest_changed = _normalized_manifest(row["manifest_json"])
        index_bytes = str(row["index_html"] or "").encode("utf-8")
        normalized_index, index_changed = _normalized_text(index_bytes)
        values: dict[str, object] = {}
        if manifest_changed:
            values["manifest_json"] = manifest
        if index_changed:
            values["index_html"] = normalized_index.decode("utf-8")
        if values:
            connection.execute(
                sa.update(templates)
                .where(templates.c.id == row["id"])
                .values(**values)
            )

    text_types = {
        "application/javascript",
        "text/javascript",
        "application/json",
        "text/css",
        "text/html",
        "text/plain",
    }
    for row in connection.execute(
        sa.select(assets.c.id, assets.c.content_type, assets.c.content)
    ).mappings():
        if row["content_type"] not in text_types or not isinstance(
            row["content"], (bytes, bytearray, memoryview)
        ):
            continue
        normalized, changed = _normalized_text(bytes(row["content"]))
        if changed:
            connection.execute(
                sa.update(assets)
                .where(assets.c.id == row["id"])
                .values(content=normalized)
            )


def downgrade() -> None:
    # Public white-label identifiers are a one-way compatibility repair. A
    # downgrade must not reintroduce product-branded globals into customer
    # bundles.
    pass
