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


class SystemCredential(Base, TimestampMixin):
    __tablename__ = "system_credentials"
    __table_args__ = (
        UniqueConstraint(
            "platform_key",
            "credential_key",
            name="uq_system_credentials_platform_credential",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    platform_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    credential_key: Mapped[str] = mapped_column(String(64), nullable=False)
    value_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    value_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    value_last4: Mapped[str] = mapped_column(String(4), default="", nullable=False)
    updated_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )


class SystemPlatformConfiguration(Base, TimestampMixin):
    __tablename__ = "system_platform_configurations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    platform_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    settings_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    last_test_status: Mapped[str] = mapped_column(
        String(24), default="untested", nullable=False, index=True
    )
    last_test_message: Mapped[str | None] = mapped_column(Text)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("user_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )


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
        CheckConstraint(
            "connection_policy IN ('on_demand', 'always_on')",
            name="ck_protocol_nodes_connection_policy",
        ),
        CheckConstraint(
            "(max_account_count IS NULL OR max_account_count >= 0) AND "
            "(max_online_accounts IS NULL OR max_online_accounts >= 0) AND "
            "(max_concurrent_pairings IS NULL OR max_concurrent_pairings >= 0)",
            name="ck_protocol_nodes_capacity_nonnegative",
        ),
        CheckConstraint(
            "idle_disconnect_seconds >= 60 AND post_verify_grace_seconds >= 0",
            name="ck_protocol_nodes_connection_windows",
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
    max_account_count: Mapped[int | None] = mapped_column(Integer)
    max_online_accounts: Mapped[int | None] = mapped_column(
        Integer, default=1000, nullable=True
    )
    max_concurrent_pairings: Mapped[int | None] = mapped_column(Integer)
    connection_policy: Mapped[str] = mapped_column(
        String(24), default="on_demand", nullable=False
    )
    idle_disconnect_seconds: Mapped[int] = mapped_column(
        Integer, default=600, nullable=False
    )
    post_verify_grace_seconds: Mapped[int] = mapped_column(
        Integer, default=120, nullable=False
    )
    sync_policy_version: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )
    sync_policy_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    rate_limit_policy_json: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    created_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_accounts.id", ondelete="CASCADE"), index=True
    )


class ProtocolPool(Base, TimestampMixin):
    __tablename__ = "protocol_pools"
    __table_args__ = (
        UniqueConstraint(
            "created_by", "name", name="uq_protocol_pools_owner_name"
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, default=next_snowflake_id
    )
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    remark: Mapped[str | None] = mapped_column(String(512))
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    created_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        index=True,
    )


class ProtocolPoolMember(Base, TimestampMixin):
    __tablename__ = "protocol_pool_members"
    __table_args__ = (
        UniqueConstraint(
            "pool_id", "protocol_node_id", name="uq_protocol_pool_member"
        ),
        CheckConstraint(
            "priority >= 0", name="ck_protocol_pool_member_priority"
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, default=next_snowflake_id
    )
    pool_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("protocol_pools.id", ondelete="CASCADE"),
        index=True,
    )
    protocol_node_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("protocol_nodes.id", ondelete="RESTRICT"),
        index=True,
    )
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


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
        CheckConstraint(
            "admission_status IN ('reserved', 'active', 'abandoned')",
            name="ck_personal_accounts_admission_status",
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
    admission_status: Mapped[str] = mapped_column(
        String(16), default="active", nullable=False, index=True
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
    marketing_eligible: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sending_cooldown_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("user_accounts.id", ondelete="RESTRICT"))

    @property
    def gateway_account_id(self) -> str:
        """Legacy Baileys identifier; never use this as the control-plane ID."""

        return self.public_id


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
        CheckConstraint(
            "onboarding_status IN ('idle', 'running', 'waiting', 'failed', 'completed')",
            name="ck_domains_onboarding_status",
        ),
        CheckConstraint(
            "onboarding_stage IN ('not_started', 'cloudflare_zone', 'registrar_nameservers', 'cloudflare_dns', 'baota_site', 'public_verification', 'completed')",
            name="ck_domains_onboarding_stage",
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
    onboarding_status: Mapped[str] = mapped_column(
        String(16), default="idle", server_default="idle", nullable=False, index=True
    )
    onboarding_stage: Mapped[str] = mapped_column(
        String(32), default="not_started", server_default="not_started", nullable=False
    )
    onboarding_state_json: Mapped[dict] = mapped_column(
        JSON, default=dict, server_default="{}", nullable=False
    )
    onboarding_message: Mapped[str | None] = mapped_column(Text)
    onboarding_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
            "status IN ('pending_payment', 'paid', 'purchase_ready', 'provisioning', 'unknown', 'completed', 'failed', 'cancelled')",
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
            "device_signals IN ('off', 'standard', 'enhanced', 'fingerprint')",
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
        String(16), default="fingerprint", nullable=False
    )
    created_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class PromotionIntegration(Base, TimestampMixin):
    __tablename__ = "promotion_integrations"
    __table_args__ = (
        UniqueConstraint(
            "created_by",
            "integration_key",
            name="uq_promotion_integration_owner_key",
        ),
        CheckConstraint(
            "integration_type IN ('script', 'iframe')",
            name="ck_promotion_integrations_type",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    integration_key: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    integration_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source_domain_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("domains.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    version: Mapped[str] = mapped_column(String(40), default="1", nullable=False)
    integrity: Mapped[str | None] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )


class PromotionTemplateIntegration(Base, TimestampMixin):
    __tablename__ = "promotion_template_integrations"
    __table_args__ = (
        UniqueConstraint(
            "template_id",
            "integration_id",
            name="uq_promotion_template_integration",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    template_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("promotion_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    integration_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("promotion_integrations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)


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
        CheckConstraint(
            "protocol_node_id IS NULL OR protocol_pool_id IS NULL",
            name="ck_promotion_channels_protocol_route",
        ),
        CheckConstraint(
            "in_app_browser_mode IN ('allow', 'guide_external')",
            name="ck_promotion_channels_in_app_browser_mode",
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
    account_group_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("account_groups.id", ondelete="RESTRICT"),
        index=True,
    )
    protocol_node_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("protocol_nodes.id", ondelete="RESTRICT"),
        index=True,
    )
    protocol_pool_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("protocol_pools.id", ondelete="RESTRICT"),
        index=True,
    )
    route_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    meta_browser_pixel_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    meta_capi_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    meta_domain_blocked: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    meta_domain_blocked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    meta_event_mapping_json: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False
    )
    in_app_browser_mode: Mapped[str] = mapped_column(
        String(24), default="allow", nullable=False
    )
    new_account_marketing_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
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
        CheckConstraint(
            "attempt_type IN ('initial', 'reauthentication')",
            name="ck_account_pairing_attempts_type",
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
        Index(
            "ix_account_pairing_attempts_channel_fingerprint_created",
            "channel_id",
            "visitor_fingerprint_hash",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, default=next_snowflake_id
    )
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    attempt_type: Mapped[str] = mapped_column(
        String(24), default="initial", nullable=False, index=True
    )
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
    account_group_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("account_groups.id", ondelete="RESTRICT"),
        index=True,
    )
    protocol_node_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("protocol_nodes.id", ondelete="RESTRICT"),
        index=True,
    )
    route_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    sync_policy_version: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )
    sync_policy_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    visitor_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    visitor_fingerprint_hash: Mapped[str | None] = mapped_column(String(64))
    fingerprint_version: Mapped[str | None] = mapped_column(String(40))
    fingerprint_quality: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(
        String(24), default="code_issued", nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_reason: Mapped[str | None] = mapped_column(String(64))
    provider_code: Mapped[str | None] = mapped_column(String(64))


class AccountMetadataSyncJob(Base, TimestampMixin):
    __tablename__ = "account_metadata_sync_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_account_metadata_sync_jobs_status",
        ),
        Index(
            "ix_account_metadata_sync_jobs_pending",
            "status",
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
    protocol_node_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("protocol_nodes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sync_policy_version: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )
    sync_policy_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="pending", nullable=False, index=True
    )
    active_key: Mapped[str | None] = mapped_column(
        String(80), unique=True, index=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )


class AccountGroupWakeupEvent(Base, TimestampMixin):
    """Durable signal that a group's dispatchable account set may have changed."""

    __tablename__ = "account_group_wakeup_events"
    __table_args__ = (
        Index(
            "ix_account_group_wakeup_events_pending",
            "processed_at",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, default=next_snowflake_id
    )
    group_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("account_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("personal_accounts.id", ondelete="SET NULL"),
        index=True,
    )
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )


class PromotionEvent(Base, TimestampMixin):
    __tablename__ = "promotion_events"
    __table_args__ = (
        UniqueConstraint("channel_id", "idempotency_key", name="uq_promotion_event_idem"),
        Index("ix_promotion_events_channel_occurred", "channel_id", "occurred_at"),
        Index("ix_promotion_events_channel_visitor", "channel_id", "visitor_id"),
        Index(
            "ix_promotion_events_channel_fingerprint",
            "channel_id",
            "visitor_fingerprint_hash",
        ),
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
    visitor_fingerprint_hash: Mapped[str | None] = mapped_column(String(64))
    fingerprint_version: Mapped[str | None] = mapped_column(String(40))
    fingerprint_quality: Mapped[str | None] = mapped_column(String(16))
    lead_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("promotion_leads.id", ondelete="SET NULL"), index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    country_code: Mapped[str | None] = mapped_column(String(2), index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class MetaConversionDelivery(Base, TimestampMixin):
    __tablename__ = "meta_conversion_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "pixel_id", "event_id", name="uq_meta_conversion_pixel_event"
        ),
        CheckConstraint(
            "status IN ('pending', 'sending', 'retry', 'delivered', 'failed', 'skipped')",
            name="ck_meta_conversion_deliveries_status",
        ),
        Index(
            "ix_meta_conversion_deliveries_due",
            "status",
            "next_attempt_at",
        ),
        Index(
            "ix_meta_conversion_deliveries_channel_created",
            "channel_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, default=next_snowflake_id
    )
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    channel_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("promotion_channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pixel_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("meta_pixels.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    promotion_event_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("promotion_events.id", ondelete="SET NULL"),
        index=True,
    )
    event_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    event_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    action_source: Mapped[str] = mapped_column(
        String(32), default="website", nullable=False
    )
    event_source_url: Mapped[str | None] = mapped_column(Text)
    user_data_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    custom_data_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="pending", nullable=False, index=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_trace_id: Mapped[str | None] = mapped_column(String(255))
    last_error: Mapped[str | None] = mapped_column(Text)


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


class Material(Base, TimestampMixin):
    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    material_type: Mapped[str] = mapped_column(String(24), index=True)
    text_role: Mapped[str | None] = mapped_column(String(16), index=True)
    content_json: Mapped[dict] = mapped_column(JSON, default=dict)
    file_name: Mapped[str | None] = mapped_column(String(180))
    content_type: Mapped[str | None] = mapped_column(String(120))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    file_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    content: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
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
        ForeignKey("materials.id", ondelete="SET NULL"), index=True
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
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
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
    package_revision: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False, index=True
    )
    removed_revision: Mapped[int | None] = mapped_column(Integer, index=True)
    validation_status: Mapped[str] = mapped_column(
        String(16), default="valid", nullable=False, index=True
    )
    last_error: Mapped[str | None] = mapped_column(Text)


class HyperlinkTask(Base, TimestampMixin):
    __tablename__ = "hyperlink_tasks"
    __table_args__ = (
        CheckConstraint(
            "sender_mode IN ('legacy_fixed', 'dynamic_group')",
            name="ck_hyperlink_tasks_sender_mode",
        ),
    )

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
    data_package_revision: Mapped[int | None] = mapped_column(Integer)
    account_group_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("account_groups.id", ondelete="RESTRICT"),
        index=True,
    )
    sender_mode: Mapped[str] = mapped_column(
        String(16), default="legacy_fixed", nullable=False, index=True
    )
    account_public_ids: Mapped[list] = mapped_column(JSON, default=list)
    channel: Mapped[str | None] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    template_name_snapshot: Mapped[str | None] = mapped_column(String(120))
    template_snapshot_json: Mapped[dict | None] = mapped_column(JSON)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    queued_count: Mapped[int] = mapped_column(Integer, default=0)
    submitting_count: Mapped[int] = mapped_column(Integer, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0)
    submission_failed_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    delivered_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    reconciling_count: Mapped[int] = mapped_column(Integer, default=0)
    cancelled_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    slot_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("hyperlink_task_account_slots.id", ondelete="SET NULL"),
        index=True,
    )
    lease_token: Mapped[str | None] = mapped_column(String(64), index=True)
    leased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    submission_status: Mapped[str] = mapped_column(
        String(16), default="pending", nullable=False, index=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    submission_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)


class HyperlinkTaskAccountSlot(Base, TimestampMixin):
    __tablename__ = "hyperlink_task_account_slots"
    __table_args__ = (
        UniqueConstraint("task_id", "slot_index", name="uq_hyperlink_task_slot_index"),
        # An account may be held by only one live task slot. Released slots clear
        # account_id, so completed history does not block future tasks.
        UniqueConstraint("account_id", name="uq_hyperlink_task_slot_account"),
        CheckConstraint(
            "status IN ('vacant', 'active', 'replacing', 'released')",
            name="ck_hyperlink_task_slot_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_snowflake_id)
    task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("hyperlink_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slot_index: Mapped[int] = mapped_column(Integer, nullable=False)
    account_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("personal_accounts.id", ondelete="SET NULL"),
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(16), default="vacant", nullable=False, index=True
    )
    lease_token: Mapped[str | None] = mapped_column(String(64), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    switch_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consecutive_failure_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    last_switch_reason: Mapped[str | None] = mapped_column(String(64))
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
