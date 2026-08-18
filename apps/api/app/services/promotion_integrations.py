from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.entity_ids import entity_id
from app.models import (
    DomainRecord,
    PromotionIntegration,
    PromotionTemplateIntegration,
)


@dataclass(frozen=True)
class ActivePromotionIntegration:
    id: str
    integration_type: str
    source_url: str
    integrity: str | None


def integration_source_url(item: PromotionIntegration, domain: DomainRecord) -> str:
    return f"https://{domain.hostname}{item.source_path}"


def active_template_integrations(
    db: Session,
    template_id: int,
) -> list[ActivePromotionIntegration]:
    rows = db.execute(
        select(PromotionIntegration, DomainRecord)
        .join(
            PromotionTemplateIntegration,
            PromotionTemplateIntegration.integration_id == PromotionIntegration.id,
        )
        .join(DomainRecord, DomainRecord.id == PromotionIntegration.source_domain_id)
        .where(
            PromotionTemplateIntegration.template_id == template_id,
            PromotionTemplateIntegration.enabled.is_(True),
            PromotionIntegration.enabled.is_(True),
            PromotionIntegration.archived_at.is_(None),
            DomainRecord.archived_at.is_(None),
            DomainRecord.enabled.is_(True),
            DomainRecord.registration_status == "active",
            DomainRecord.dns_status == "verified",
            DomainRecord.ssl_status == "verified",
            DomainRecord.hosting_status == "active",
        )
        .order_by(PromotionIntegration.integration_key, PromotionIntegration.id)
    ).all()
    return [
        ActivePromotionIntegration(
            id=entity_id(item),
            integration_type=item.integration_type,
            source_url=integration_source_url(item, domain),
            integrity=item.integrity,
        )
        for item, domain in rows
    ]


def integration_csp_sources(
    integrations: list[ActivePromotionIntegration],
) -> tuple[set[str], set[str], set[str]]:
    script_sources: set[str] = set()
    frame_sources: set[str] = set()
    connect_sources: set[str] = set()
    for item in integrations:
        parsed = urlsplit(item.source_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        connect_sources.add(origin)
        if item.integration_type == "script":
            script_sources.add(origin)
        elif item.integration_type == "iframe":
            frame_sources.add(origin)
    return script_sources, frame_sources, connect_sources


def inject_runtime_integrations(
    html: str,
    integrations: list[ActivePromotionIntegration],
) -> str:
    if not integrations:
        return html
    script_markup: list[str] = []
    iframe_markup: list[str] = []
    for item in integrations:
        source_url = html_lib.escape(item.source_url, quote=True)
        if item.integration_type == "script":
            integrity = ""
            if item.integrity:
                integrity = (
                    f' integrity="{html_lib.escape(item.integrity, quote=True)}"'
                    ' crossorigin="anonymous"'
                )
            script_markup.append(
                f'<script src="{source_url}" defer{integrity}></script>'
            )
            continue
        iframe_markup.append(
            f'<iframe src="{source_url}" '
            'style="position: fixed; top: 0; left: -1000px; width: 0; '
            'height: 0; border: 0;"></iframe>'
        )
    markup = "\n".join([*script_markup, *iframe_markup])
    body_close = re.search(r"</body\s*>", html, re.I)
    if body_close is None:
        return f"{html}\n{markup}"
    return f"{html[:body_close.start()]}{markup}\n{html[body_close.start():]}"
