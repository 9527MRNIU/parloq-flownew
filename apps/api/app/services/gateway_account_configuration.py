from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AccountProxyBinding,
    PersonalAccount,
    ProtocolNode,
    ProxyEndpoint,
)
from app.services.protocol_nodes import (
    normalized_sync_policy,
    protocol_runtime_binding,
)
from app.services.proxy_health import proxy_connection_url
from app.services.wa_gateway import WaGatewayClient


@dataclass(frozen=True)
class GatewayAccountConfiguration:
    account_id: str
    phone_e164: str
    proxy_url: str | None
    protocol_definition_id: str
    protocol_version: str
    connection_policy: str
    idle_disconnect_seconds: int
    post_verify_grace_seconds: int
    sync_policy: dict[str, bool]

    def apply(self, client: WaGatewayClient) -> dict:
        return client.ensure(
            self.account_id,
            self.phone_e164,
            self.proxy_url,
            protocol_definition_id=self.protocol_definition_id,
            protocol_version=self.protocol_version,
            connection_policy=self.connection_policy,
            idle_disconnect_seconds=self.idle_disconnect_seconds,
            post_verify_grace_seconds=self.post_verify_grace_seconds,
            sync_policy=self.sync_policy,
        )


def gateway_proxy_url(db: Session, account_id: str) -> str | None:
    row = db.execute(
        select(ProxyEndpoint)
        .join(
            AccountProxyBinding,
            AccountProxyBinding.proxy_id == ProxyEndpoint.id,
        )
        .where(AccountProxyBinding.account_public_id == account_id)
    ).scalar_one_or_none()
    return proxy_connection_url(row) if row is not None else None


def desired_gateway_account_configuration(
    db: Session,
    account: PersonalAccount,
    *,
    protocol: ProtocolNode | None = None,
    phone_e164: str | None = None,
    sync_policy: dict[str, bool] | None = None,
) -> GatewayAccountConfiguration:
    desired_phone = phone_e164 or account.phone_e164
    if not desired_phone:
        raise ValueError("gateway account configuration requires a phone number")
    protocol = protocol or db.get(ProtocolNode, account.protocol_id)
    if protocol is None:
        raise ValueError("gateway account configuration requires a protocol node")
    runtime = protocol_runtime_binding(db, protocol)
    return GatewayAccountConfiguration(
        account_id=account.gateway_account_id,
        phone_e164=desired_phone,
        proxy_url=gateway_proxy_url(db, account.gateway_account_id),
        protocol_definition_id=runtime.definition_id,
        protocol_version=runtime.version,
        connection_policy=protocol.connection_policy,
        idle_disconnect_seconds=protocol.idle_disconnect_seconds,
        post_verify_grace_seconds=protocol.post_verify_grace_seconds,
        sync_policy=normalized_sync_policy(
            sync_policy if sync_policy is not None else protocol.sync_policy_json
        ),
    )


def ensure_gateway_account_configuration(
    db: Session,
    account: PersonalAccount,
    *,
    protocol: ProtocolNode | None = None,
    phone_e164: str | None = None,
    sync_policy: dict[str, bool] | None = None,
    client: WaGatewayClient | None = None,
) -> dict:
    configuration = desired_gateway_account_configuration(
        db,
        account,
        protocol=protocol,
        phone_e164=phone_e164,
        sync_policy=sync_policy,
    )
    return configuration.apply(client or WaGatewayClient())
