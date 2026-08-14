from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.snowflake import next_snowflake_id


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UserGroup(Base, TimestampMixin):
    __tablename__ = "user_groups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    system_key: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    users: Mapped[list[UserAccount]] = relationship(back_populates="group")
    menu_permissions: Mapped[list[RoleMenuPermission]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )
    action_permissions: Mapped[list[RoleActionPermission]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )


class UserAccount(Base, TimestampMixin):
    __tablename__ = "user_accounts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(120))
    group_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_groups.id", ondelete="RESTRICT"), index=True
    )
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(32), default="operator", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    group: Mapped[UserGroup] = relationship(back_populates="users")
    sessions: Mapped[list[AuthSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class AuthSession(Base, TimestampMixin):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_accounts.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    user: Mapped[UserAccount] = relationship(back_populates="sessions")


class SystemMenu(Base, TimestampMixin):
    __tablename__ = "system_menus"
    __table_args__ = (
        CheckConstraint("menu_type IN ('directory', 'page')", name="ck_system_menus_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("system_menus.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(80), index=True)
    menu_type: Mapped[str] = mapped_column(String(16), default="page", nullable=False)
    route_path: Mapped[str | None] = mapped_column(String(255), unique=True)
    icon: Mapped[str | None] = mapped_column(String(80))
    permission_key: Mapped[str | None] = mapped_column(String(120), unique=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    visible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    parent: Mapped[SystemMenu | None] = relationship(remote_side="SystemMenu.id")
    role_permissions: Mapped[list[RoleMenuPermission]] = relationship(
        back_populates="menu", cascade="all, delete-orphan"
    )


class RoleMenuPermission(Base, TimestampMixin):
    __tablename__ = "role_menu_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "menu_id", name="uq_role_menu_permission"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    role_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_groups.id", ondelete="CASCADE"), index=True
    )
    menu_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("system_menus.id", ondelete="CASCADE"), index=True
    )

    role: Mapped[UserGroup] = relationship(back_populates="menu_permissions")
    menu: Mapped[SystemMenu] = relationship(back_populates="role_permissions")


class RoleActionPermission(Base, TimestampMixin):
    __tablename__ = "role_action_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_key", name="uq_role_action_permission"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    role_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_groups.id", ondelete="CASCADE"), index=True
    )
    permission_key: Mapped[str] = mapped_column(String(120), index=True)

    role: Mapped[UserGroup] = relationship(back_populates="action_permissions")


class BitlyProviderAccount(Base, TimestampMixin):
    __tablename__ = "bitly_provider_accounts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    token_ciphertext: Mapped[str] = mapped_column(Text)
    token_fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    token_last4: Mapped[str] = mapped_column(String(4), default="", nullable=False)
    group_guid: Mapped[str] = mapped_column(String(80))
    short_domain: Mapped[str] = mapped_column(String(255), default="bit.ly")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    links: Mapped[list[DirectShortLink]] = relationship(back_populates="provider_account")


class DirectShortLink(Base, TimestampMixin):
    __tablename__ = "direct_short_links"
    __table_args__ = (
        Index("ix_direct_short_links_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(255))
    target_url: Mapped[str] = mapped_column(Text)
    bitlink_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    short_url: Mapped[str] = mapped_column(Text)
    provider_account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bitly_provider_accounts.id", ondelete="RESTRICT"), index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_accounts.id", ondelete="RESTRICT"), index=True
    )

    provider_account: Mapped[BitlyProviderAccount] = relationship(back_populates="links")


class MetaPixel(Base, TimestampMixin):
    __tablename__ = "meta_pixels"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    dataset_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    capi_token_ciphertext: Mapped[str | None] = mapped_column(Text)
    capi_token_last4: Mapped[str] = mapped_column(String(4), default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_accounts.id", ondelete="RESTRICT"), index=True
    )


class ProxyEndpoint(Base, TimestampMixin):
    __tablename__ = "proxy_endpoints"
    __table_args__ = (
        CheckConstraint(
            "protocol IN ('http', 'https', 'socks5')",
            name="ck_proxy_endpoints_protocol",
        ),
        CheckConstraint(
            "health_status IN ('untested', 'healthy', 'unhealthy')",
            name="ck_proxy_endpoints_health_status",
        ),
        CheckConstraint("port >= 1 AND port <= 65535", name="ck_proxy_endpoints_port"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    protocol: Mapped[str] = mapped_column(String(16), index=True)
    host: Mapped[str] = mapped_column(String(255), index=True)
    port: Mapped[int] = mapped_column(Integer)
    username_ciphertext: Mapped[str | None] = mapped_column(Text)
    username_last4: Mapped[str] = mapped_column(String(4), default="", nullable=False)
    password_ciphertext: Mapped[str | None] = mapped_column(Text)
    password_last4: Mapped[str] = mapped_column(String(4), default="", nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(2), index=True)
    provider: Mapped[str | None] = mapped_column(String(120), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    health_status: Mapped[str] = mapped_column(
        String(16), default="untested", nullable=False, index=True
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    bindings: Mapped[list[AccountProxyBinding]] = relationship(back_populates="proxy")


class IpAllocationPolicy(Base, TimestampMixin):
    __tablename__ = "ip_allocation_policies"
    __table_args__ = (
        CheckConstraint(
            "allocation_mode IN ('strict_one_to_one', 'tenant_reuse', 'least_load', 'manual')",
            name="ck_ip_allocation_policies_mode",
        ),
        CheckConstraint(
            "country_match IN ('strict', 'prefer', 'off')",
            name="ck_ip_allocation_policies_country_match",
        ),
        CheckConstraint(
            "max_accounts_per_ip >= 1 AND max_accounts_per_ip <= 10000",
            name="ck_ip_allocation_policies_max_accounts",
        ),
        UniqueConstraint("created_by", name="uq_ip_allocation_policies_owner"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    allocation_mode: Mapped[str] = mapped_column(
        String(24), default="least_load", nullable=False, index=True
    )
    country_match: Mapped[str] = mapped_column(
        String(16), default="prefer", nullable=False, index=True
    )
    max_accounts_per_ip: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    avoid_unhealthy: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sticky_binding: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_accounts.id", ondelete="CASCADE"), index=True
    )


class AccountProxyBinding(Base, TimestampMixin):
    __tablename__ = "account_proxy_bindings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    account_public_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    proxy_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("proxy_endpoints.id", ondelete="RESTRICT"), index=True
    )

    proxy: Mapped[ProxyEndpoint] = relationship(back_populates="bindings")


class AccountGroup(Base, TimestampMixin):
    __tablename__ = "account_groups"
    __table_args__ = (
        UniqueConstraint("created_by", "name", name="uq_account_groups_owner_name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_accounts.id", ondelete="RESTRICT"), index=True
    )


class ProtocolNode(Base, TimestampMixin):
    __tablename__ = "protocol_nodes"
    __table_args__ = (
        CheckConstraint(
            "protocol_type IN ('baileys')", name="ck_protocol_nodes_type"
        ),
        UniqueConstraint(
            "created_by", "name", name="uq_protocol_nodes_owner_name"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    protocol_type: Mapped[str] = mapped_column(
        String(24), default="baileys", nullable=False, index=True
    )
    remark: Mapped[str | None] = mapped_column(String(512))
    ingress_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
    marketing_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
    online_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    created_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_accounts.id", ondelete="CASCADE"), index=True
    )


class PersonalAccount(Base, TimestampMixin):
    __tablename__ = "personal_accounts"
    __table_args__ = (
        CheckConstraint(
            "source IN ('landing_page', 'json_import')",
            name="ck_personal_accounts_source",
        ),
        CheckConstraint(
            "validation_status IN ('pending', 'validating', 'ready', 'failed')",
            name="ck_personal_accounts_validation_status",
        ),
        CheckConstraint(
            "metadata_sync_status IN ('pending', 'syncing', 'ready', 'failed', 'unsupported')",
            name="ck_personal_accounts_metadata_sync_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    phone_e164: Mapped[str | None] = mapped_column(String(20), unique=True, index=True)
    country_code: Mapped[str | None] = mapped_column(String(2), index=True)
    status: Mapped[str] = mapped_column(String(32), default="unpaired", index=True)
    source: Mapped[str] = mapped_column(
        String(24), default="landing_page", nullable=False, index=True
    )
    source_ref_type: Mapped[str | None] = mapped_column(String(40), index=True)
    source_ref_id: Mapped[str | None] = mapped_column(String(64), index=True)
    import_format: Mapped[str | None] = mapped_column(String(40), index=True)
    validation_status: Mapped[str] = mapped_column(
        String(16), default="pending", nullable=False, index=True
    )
    metadata_sync_status: Mapped[str] = mapped_column(
        String(16), default="pending", nullable=False, index=True
    )
    group_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("account_groups.id", ondelete="SET NULL"), index=True
    )
    protocol_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("protocol_nodes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    has_avatar: Mapped[bool | None] = mapped_column(Boolean)
    group_count: Mapped[int | None] = mapped_column(Integer)
    friend_count: Mapped[int | None] = mapped_column(Integer)
    mutual_contact_count: Mapped[int | None] = mapped_column(Integer)
    quality_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("user_accounts.id", ondelete="RESTRICT"))


class AccountLifecycleEvent(Base):
    __tablename__ = "account_lifecycle_events"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "public_id",
            name="uq_account_lifecycle_account_event",
        ),
        Index(
            "ix_account_lifecycle_events_account_occurred",
            "account_id",
            "occurred_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("personal_accounts.id", ondelete="CASCADE"), index=True
    )
    from_state: Mapped[str | None] = mapped_column(String(32))
    to_state: Mapped[str] = mapped_column(String(32), index=True)
    reason_category: Mapped[str | None] = mapped_column(String(64))
    provider_code: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AccountAnalyticsState(Base):
    __tablename__ = "account_analytics_state"
    __table_args__ = (
        CheckConstraint("singleton_key = 'global'", name="ck_account_analytics_state_singleton"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    singleton_key: Mapped[str] = mapped_column(
        String(16), default="global", server_default="global", unique=True, nullable=False
    )
    collection_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MessageDelivery(Base, TimestampMixin):
    __tablename__ = "message_deliveries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    request_id: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("personal_accounts.id", ondelete="RESTRICT"), index=True
    )
    recipient_e164: Mapped[str] = mapped_column(String(20), index=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class DomainRecord(Base, TimestampMixin):
    __tablename__ = "domains"
    __table_args__ = (
        CheckConstraint(
            "acquisition_type IN ('connected', 'purchased')",
            name="ck_domains_acquisition_type",
        ),
        CheckConstraint(
            "management_mode IN ('external', 'platform')",
            name="ck_domains_management_mode",
        ),
        CheckConstraint(
            "registration_status IN ('active', 'pending', 'failed', 'expired')",
            name="ck_domains_registration_status",
        ),
        CheckConstraint(
            "hosting_status IN ('pending', 'active', 'failed')",
            name="ck_domains_hosting_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    hostname: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    acquisition_type: Mapped[str] = mapped_column(
        String(16), default="connected", nullable=False, index=True
    )
    management_mode: Mapped[str] = mapped_column(
        String(16), default="external", nullable=False, index=True
    )
    registrar_provider: Mapped[str | None] = mapped_column(String(80))
    registration_status: Mapped[str] = mapped_column(
        String(16), default="active", nullable=False, index=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    hosting_provider: Mapped[str] = mapped_column(
        String(80), default="cloudflare", nullable=False
    )
    hosting_status: Mapped[str] = mapped_column(
        String(16), default="pending", nullable=False, index=True
    )
    verification_token: Mapped[str] = mapped_column(String(80), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    dns_status: Mapped[str] = mapped_column(String(16), default="untested", index=True)
    ssl_status: Mapped[str] = mapped_column(String(16), default="untested", index=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_accounts.id", ondelete="RESTRICT"), index=True
    )


class DomainQuote(Base, TimestampMixin):
    __tablename__ = "domain_quotes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    hostname: Mapped[str] = mapped_column(String(255), index=True)
    years: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_accounts.id", ondelete="RESTRICT"), index=True
    )


class DomainOrder(Base, TimestampMixin):
    __tablename__ = "domain_orders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_payment', 'paid', 'provisioning', 'unknown', 'completed', 'failed', 'cancelled')",
            name="ck_domain_orders_status",
        ),
        CheckConstraint("years >= 1 AND years <= 10", name="ck_domain_orders_years"),
        CheckConstraint("amount >= 0", name="ck_domain_orders_amount"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    quote_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("domain_quotes.id", ondelete="RESTRICT"), unique=True, index=True
    )
    hostname: Mapped[str] = mapped_column(String(255), index=True)
    years: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default="pending_payment", nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(80), default="mock", nullable=False)
    provider_order_ref: Mapped[str | None] = mapped_column(String(160), unique=True)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    domain_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("domains.id", ondelete="SET NULL"), unique=True, index=True
    )
    created_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_accounts.id", ondelete="RESTRICT"), index=True
    )


class PromotionTemplate(Base, TimestampMixin):
    __tablename__ = "promotion_templates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(40), default="1")
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    manifest_json: Mapped[dict] = mapped_column(JSON, default=dict)
    index_html: Mapped[str] = mapped_column(Text)
    asset_count: Mapped[int] = mapped_column(Integer, default=0)
    total_size: Mapped[int] = mapped_column(Integer, default=0)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_accounts.id", ondelete="RESTRICT"), index=True
    )


class PromotionTemplatePolicy(Base, TimestampMixin):
    __tablename__ = "promotion_template_policies"
    __table_args__ = (
        UniqueConstraint("created_by", name="uq_promotion_template_policy_owner"),
        CheckConstraint(
            "protection_mode IN ('basic', 'enhanced', 'strict')",
            name="ck_promotion_template_policy_protection_mode",
        ),
        CheckConstraint(
            "devtools_action IN ('log', 'block', 'blank')",
            name="ck_promotion_template_policy_devtools_action",
        ),
        CheckConstraint(
            "device_signals IN ('off', 'standard', 'enhanced')",
            name="ck_promotion_template_policy_device_signals",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    protection_mode: Mapped[str] = mapped_column(
        String(16), default="strict", nullable=False
    )
    devtools_action: Mapped[str] = mapped_column(
        String(16), default="blank", nullable=False
    )
    lock_viewport_zoom: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    device_signals: Mapped[str] = mapped_column(
        String(16), default="enhanced", nullable=False
    )
    created_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class PromotionAsset(Base, TimestampMixin):
    __tablename__ = "promotion_assets"
    __table_args__ = (
        UniqueConstraint("template_id", "path", name="uq_promotion_asset_path"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    template_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("promotion_templates.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(Integer)
    content: Mapped[bytes] = mapped_column(LargeBinary)


class PromotionChannel(Base, TimestampMixin):
    __tablename__ = "promotion_channels"
    __table_args__ = (
        UniqueConstraint(
            "domain_id",
            "subdomain_prefix",
            "slug",
            name="uq_promotion_channel_domain_subdomain_slug",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    channel_type: Mapped[str] = mapped_column(String(24), default="facebook", index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    country_code: Mapped[str] = mapped_column(String(2), index=True)
    template_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("promotion_templates.id", ondelete="RESTRICT"), index=True
    )
    domain_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("domains.id", ondelete="RESTRICT"), index=True
    )
    subdomain_prefix: Mapped[str] = mapped_column(
        String(63), default="", server_default="", index=True
    )
    slug: Mapped[str] = mapped_column(String(120), index=True)
    pixel_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("meta_pixels.id", ondelete="SET NULL"), index=True
    )
    locale_mode: Mapped[str] = mapped_column(String(16), default="auto")
    locale: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    launch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_accounts.id", ondelete="RESTRICT"), index=True
    )


class AccountPairingAttempt(Base, TimestampMixin):
    __tablename__ = "account_pairing_attempts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('code_issued', 'waiting_phone', 'reconnecting', 'verified', 'expired', 'cancelled', 'failed')",
            name="ck_account_pairing_attempts_status",
        ),
        Index(
            "ix_account_pairing_attempts_account_created",
            "account_id",
            "created_at",
        ),
        Index(
            "ix_account_pairing_attempts_channel_visitor_created",
            "channel_id",
            "visitor_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, default=next_snowflake_id
    )
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("personal_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("promotion_channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    visitor_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(24), default="code_issued", nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_reason: Mapped[str | None] = mapped_column(String(64))
    provider_code: Mapped[str | None] = mapped_column(String(64))


class PromotionEvent(Base, TimestampMixin):
    __tablename__ = "promotion_events"
    __table_args__ = (
        UniqueConstraint("channel_id", "idempotency_key", name="uq_promotion_event_idem"),
        Index("ix_promotion_events_channel_occurred", "channel_id", "occurred_at"),
        Index("ix_promotion_events_channel_visitor", "channel_id", "visitor_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    channel_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("promotion_channels.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    visitor_id: Mapped[str | None] = mapped_column(String(80))
    lead_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("promotion_leads.id", ondelete="SET NULL"), index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    country_code: Mapped[str | None] = mapped_column(String(2), index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class PromotionLead(Base, TimestampMixin):
    __tablename__ = "promotion_leads"
    __table_args__ = (
        UniqueConstraint("channel_id", "phone_e164", name="uq_promotion_lead_phone"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    channel_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("promotion_channels.id", ondelete="CASCADE"), index=True
    )
    phone_e164: Mapped[str] = mapped_column(String(20), index=True)
    country_code: Mapped[str | None] = mapped_column(String(2), index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    submission_count: Mapped[int] = mapped_column(Integer, default=1)


class HyperlinkMaterial(Base, TimestampMixin):
    __tablename__ = "hyperlink_materials"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    material_type: Mapped[str] = mapped_column(String(24), index=True)
    content_json: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_accounts.id", ondelete="RESTRICT"), index=True
    )


class HyperlinkTemplate(Base, TimestampMixin):
    __tablename__ = "hyperlink_templates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    content_json: Mapped[dict] = mapped_column(JSON, default=dict)
    material_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("hyperlink_materials.id", ondelete="SET NULL"), index=True
    )
    promotion_channel_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("promotion_channels.id", ondelete="SET NULL"), index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_accounts.id", ondelete="RESTRICT"), index=True
    )


class HyperlinkStrategy(Base, TimestampMixin):
    __tablename__ = "hyperlink_strategies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    max_qps: Mapped[int] = mapped_column(Integer, default=10)
    concurrency: Mapped[int] = mapped_column(Integer, default=1)
    batch_size: Mapped[int] = mapped_column(Integer, default=100)
    retry_limit: Mapped[int] = mapped_column(Integer, default=1)
    rules_json: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_accounts.id", ondelete="RESTRICT"), index=True
    )


class DataPackage(Base, TimestampMixin):
    __tablename__ = "data_packages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(16), default="ready", index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_accounts.id", ondelete="RESTRICT"), index=True
    )


class DataPackageRecipient(Base, TimestampMixin):
    __tablename__ = "data_package_recipients"
    __table_args__ = (
        UniqueConstraint("data_package_id", "phone_e164", name="uq_data_package_phone"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    data_package_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("data_packages.id", ondelete="CASCADE"), index=True
    )
    phone_e164: Mapped[str] = mapped_column(String(20), index=True)
    country_code: Mapped[str | None] = mapped_column(String(2), index=True)
    variables_json: Mapped[dict] = mapped_column(JSON, default=dict)


class HyperlinkTask(Base, TimestampMixin):
    __tablename__ = "hyperlink_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    template_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("hyperlink_templates.id", ondelete="RESTRICT"), index=True
    )
    strategy_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("hyperlink_strategies.id", ondelete="RESTRICT"), index=True
    )
    data_package_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("data_packages.id", ondelete="RESTRICT"), index=True
    )
    account_public_ids: Mapped[list] = mapped_column(JSON, default=list)
    channel: Mapped[str | None] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    queued_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    delivered_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_accounts.id", ondelete="RESTRICT"), index=True
    )


class HyperlinkTaskDelivery(Base, TimestampMixin):
    __tablename__ = "hyperlink_task_deliveries"
    __table_args__ = (
        UniqueConstraint("task_id", "recipient_id", name="uq_task_recipient_delivery"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("hyperlink_tasks.id", ondelete="CASCADE"), index=True
    )
    recipient_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("data_package_recipients.id", ondelete="RESTRICT"), index=True
    )
    account_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("personal_accounts.id", ondelete="SET NULL"), index=True
    )
    message_delivery_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("message_deliveries.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)


class AdMetric(Base, TimestampMixin):
    __tablename__ = "ad_metrics"
    __table_args__ = (
        UniqueConstraint("metric_date", "promotion_channel_id", name="uq_ad_metric_slice"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    metric_date: Mapped[date] = mapped_column(Date, index=True)
    promotion_channel_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("promotion_channels.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(80), index=True)
    country_code: Mapped[str] = mapped_column(String(2), index=True)
    spend: Mapped[float] = mapped_column(Numeric(18, 6), default=0)
    ad_fee_rate: Mapped[float] = mapped_column(Numeric(9, 4), default=0)
    other_cost: Mapped[float] = mapped_column(Numeric(18, 6), default=0)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
