from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException


@dataclass(frozen=True, slots=True)
class ProtocolAdapterDefinition:
    key: str
    display_name: str
    repository_url: str
    package_name: str
    contract_version: int


BAILEYS_ADAPTER = ProtocolAdapterDefinition(
    key="baileys",
    display_name="Baileys",
    repository_url="https://github.com/WhiskeySockets/Baileys",
    package_name="@whiskeysockets/baileys",
    contract_version=1,
)

PROTOCOL_ADAPTERS: dict[str, ProtocolAdapterDefinition] = {
    BAILEYS_ADAPTER.key: BAILEYS_ADAPTER,
}


def protocol_adapter(key: str) -> ProtocolAdapterDefinition:
    adapter = PROTOCOL_ADAPTERS.get(key)
    if adapter is None:
        raise HTTPException(status_code=422, detail="当前协议适配器尚未接入")
    return adapter


def validate_protocol_source(
    *,
    adapter_key: str,
    repository_url: str,
    package_name: str,
) -> ProtocolAdapterDefinition:
    adapter = protocol_adapter(adapter_key)
    if repository_url.rstrip("/") != adapter.repository_url:
        raise HTTPException(
            status_code=422,
            detail="实现仓库必须使用该适配器登记的受控仓库",
        )
    if package_name != adapter.package_name:
        raise HTTPException(
            status_code=422,
            detail="NPM 软件包必须使用该适配器登记的受控软件包",
        )
    return adapter
