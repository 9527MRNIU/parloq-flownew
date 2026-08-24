from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.services.baileys_credentials import validate_baileys_session
from app.services.wa_gateway import WaGatewayClient


class ProtocolSessionImportError(ValueError):
    """Safe import error that never includes credential material."""


@dataclass(frozen=True)
class ValidatedProtocolSession:
    value: dict[str, Any]
    phone_e164: str
    display_name: str | None
    import_format: str


@dataclass(frozen=True)
class ProtocolSessionImporter:
    formats: tuple[str, ...]
    validate: Callable[[Any], ValidatedProtocolSession]
    import_to_gateway: Callable[
        [WaGatewayClient, str, dict[str, Any], str | None, str, str], None
    ]


def _validate_baileys(value: Any) -> ValidatedProtocolSession:
    validated = validate_baileys_session(value)
    return ValidatedProtocolSession(
        value=validated.value,
        phone_e164=validated.phone_e164,
        display_name=validated.display_name,
        import_format=validated.import_format,
    )


def _import_baileys(
    client: WaGatewayClient,
    account_id: str,
    session: dict[str, Any],
    proxy_url: str | None,
    protocol_definition_id: str,
    protocol_version: str,
) -> None:
    client.import_session(
        account_id,
        session,
        proxy_url,
        protocol_definition_id=protocol_definition_id,
        protocol_version=protocol_version,
    )


_IMPORTERS = {
    "baileys": ProtocolSessionImporter(
        formats=("baileys_creds_json", "parloq_baileys_session_v1"),
        validate=_validate_baileys,
        import_to_gateway=_import_baileys,
    ),
}


def protocol_session_import_formats(protocol_type: str) -> tuple[str, ...]:
    importer = _IMPORTERS.get(protocol_type)
    return importer.formats if importer is not None else ()


def validate_protocol_session(
    protocol_type: str, value: Any
) -> ValidatedProtocolSession:
    importer = _IMPORTERS.get(protocol_type)
    if importer is None:
        raise ProtocolSessionImportError(
            f"{protocol_type} 协议暂不支持会话文件导入"
        )
    try:
        return importer.validate(value)
    except ValueError as exc:
        raise ProtocolSessionImportError(str(exc)) from None


def import_protocol_session(
    client: WaGatewayClient,
    protocol_type: str,
    account_id: str,
    session: dict[str, Any],
    proxy_url: str | None,
    protocol_definition_id: str,
    protocol_version: str,
) -> None:
    importer = _IMPORTERS.get(protocol_type)
    if importer is None:
        raise ProtocolSessionImportError(
            f"{protocol_type} 协议暂不支持会话文件导入"
        )
    importer.import_to_gateway(
        client,
        account_id,
        session,
        proxy_url,
        protocol_definition_id,
        protocol_version,
    )
