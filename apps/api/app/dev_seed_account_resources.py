from __future__ import annotations

import base64
import hashlib
import time
from datetime import timedelta

from sqlalchemy import delete, or_, select

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    AccountContact,
    AccountGroup,
    AccountLifecycleEvent,
    AccountWhatsappGroup,
    PersonalAccount,
    ProtocolNode,
    UserAccount,
)
from app.security import utcnow
from app.services.protocol_nodes import normalized_sync_policy
from app.services.wa_gateway import GatewayError, WaGatewayClient
from app.snowflake import new_public_id


DEMO_PUBLIC_ID = "dev_account_resource_demo"
DEMO_PHONE = "+12025550188"
IOS_DEMO_PUBLIC_ID = "dev_account_ios_demo"
IOS_DEMO_PHONE = "+14155550199"
DEMO_GROUP_NAME = "DEV · 账户资源同步演示"


def _demo_avatar() -> bytes:
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )


def seed() -> str:
    settings = get_settings()
    if settings.environment not in {"development", "test"}:
        raise RuntimeError("开发测试数据只能写入 development 或 test 环境")

    with SessionLocal() as db:
        admin = db.scalar(
            select(UserAccount)
            .where(UserAccount.role == "admin", UserAccount.is_active.is_(True))
            .order_by(UserAccount.id)
        )
        protocol = db.scalar(
            select(ProtocolNode)
            .where(ProtocolNode.online_enabled.is_(True))
            .order_by(ProtocolNode.id)
        )
        if admin is None or protocol is None:
            raise RuntimeError("请先启动 API，让系统创建管理员和默认协议节点")

        group = db.scalar(
            select(AccountGroup).where(
                AccountGroup.created_by == admin.id,
                AccountGroup.name == DEMO_GROUP_NAME,
            )
        )
        if group is None:
            group = AccountGroup(
                public_id=new_public_id("wag"),
                name=DEMO_GROUP_NAME,
                description="仅用于本地查看好友、群组、账户类型和评分页面。",
                created_by=admin.id,
            )
            db.add(group)
            db.flush()

        account = db.scalar(
            select(PersonalAccount).where(
                or_(
                    PersonalAccount.public_id == DEMO_PUBLIC_ID,
                    PersonalAccount.phone_e164 == DEMO_PHONE,
                )
            )
        )
        if account is None:
            account = PersonalAccount(
                public_id=DEMO_PUBLIC_ID,
                name="演示商业账号",
                phone_e164=DEMO_PHONE,
                country_code="US",
                status="linked_offline",
                source="json_import",
                source_ref_type="dev_fixture",
                import_format="parloq_demo",
                validation_status="ready",
                metadata_sync_status="ready",
                admission_status="active",
                group_id=group.id,
                protocol_id=protocol.id,
                enabled=True,
                marketing_eligible=True,
                created_by=admin.id,
            )
            db.add(account)
            db.flush()

        now = utcnow()
        avatar = _demo_avatar()
        account.name = "演示商业账号"
        account.phone_e164 = DEMO_PHONE
        account.country_code = "US"
        account.status = "linked_offline"
        account.source = "json_import"
        account.source_ref_type = "dev_fixture"
        account.import_format = "parloq_demo"
        account.validation_status = "ready"
        account.metadata_sync_status = "ready"
        account.admission_status = "active"
        account.group_id = group.id
        account.protocol_id = protocol.id
        account.has_avatar = True
        account.avatar_source_url = "dev-fixture://account-avatar"
        account.avatar_content_type = "image/png"
        account.avatar_size = len(avatar)
        account.avatar_sha256 = hashlib.sha256(avatar).hexdigest()
        account.avatar_content = avatar
        account.avatar_fetched_at = now
        account.friend_count = 25
        account.group_count = 8
        account.unique_group_member_count = 73
        account.wa_platform_raw = "smba"
        account.account_type = "business"
        account.device_os = "android"
        account.quality_synced_at = now
        account.resource_sync_state_json = {
            "appliedPolicyVersion": protocol.sync_policy_version,
            "contacts": {
                "status": "complete",
                "complete": True,
                "count": 25,
                "syncedAt": now.isoformat(),
            },
            "groups": {
                "status": "complete",
                "identityMappingComplete": True,
                "count": 8,
                "uniqueMemberCount": 73,
                "syncedAt": now.isoformat(),
            },
        }
        account.enabled = True
        account.marketing_eligible = True
        account.last_error = None
        account.last_connected_at = now - timedelta(minutes=18)

        ios_account = db.scalar(
            select(PersonalAccount).where(
                or_(
                    PersonalAccount.public_id == IOS_DEMO_PUBLIC_ID,
                    PersonalAccount.phone_e164 == IOS_DEMO_PHONE,
                )
            )
        )
        if ios_account is None:
            ios_account = PersonalAccount(
                public_id=IOS_DEMO_PUBLIC_ID,
                name="演示 iPhone 账号",
                phone_e164=IOS_DEMO_PHONE,
                country_code="US",
                status="linked_offline",
                source="json_import",
                source_ref_type="dev_fixture",
                import_format="parloq_ios_demo",
                validation_status="ready",
                metadata_sync_status="ready",
                admission_status="active",
                group_id=group.id,
                protocol_id=protocol.id,
                enabled=True,
                marketing_eligible=True,
                created_by=admin.id,
            )
            db.add(ios_account)
            db.flush()

        ios_account.name = "演示 iPhone 账号"
        ios_account.phone_e164 = IOS_DEMO_PHONE
        ios_account.country_code = "US"
        ios_account.status = "linked_offline"
        ios_account.source = "json_import"
        ios_account.source_ref_type = "dev_fixture"
        ios_account.import_format = "parloq_ios_demo"
        ios_account.validation_status = "ready"
        ios_account.metadata_sync_status = "ready"
        ios_account.admission_status = "active"
        ios_account.group_id = group.id
        ios_account.protocol_id = protocol.id
        ios_account.has_avatar = False
        ios_account.avatar_source_url = None
        ios_account.avatar_content_type = None
        ios_account.avatar_size = None
        ios_account.avatar_sha256 = None
        ios_account.avatar_content = None
        ios_account.avatar_fetched_at = None
        ios_account.friend_count = 0
        ios_account.group_count = 0
        ios_account.unique_group_member_count = 0
        ios_account.wa_platform_raw = "iphone"
        ios_account.account_type = "personal"
        ios_account.device_os = "ios"
        ios_account.quality_synced_at = now
        ios_account.resource_sync_state_json = {
            "appliedPolicyVersion": protocol.sync_policy_version,
            "contacts": {
                "status": "complete",
                "complete": True,
                "count": 0,
                "syncedAt": now.isoformat(),
            },
            "groups": {
                "status": "complete",
                "identityMappingComplete": True,
                "count": 0,
                "uniqueMemberCount": 0,
                "syncedAt": now.isoformat(),
            },
        }
        ios_account.enabled = True
        ios_account.marketing_eligible = True
        ios_account.last_error = None
        ios_account.last_connected_at = now - timedelta(minutes=42)

        db.execute(
            delete(AccountContact).where(AccountContact.account_id == account.id)
        )
        db.execute(
            delete(AccountWhatsappGroup).where(
                AccountWhatsappGroup.account_id == account.id
            )
        )
        db.execute(
            delete(AccountContact).where(
                AccountContact.account_id == ios_account.id
            )
        )
        db.execute(
            delete(AccountWhatsappGroup).where(
                AccountWhatsappGroup.account_id == ios_account.id
            )
        )
        for index in range(1, 26):
            saved = index <= 15 or index > 20
            contacted = index > 10
            phone = f"+12025552{index:03d}"
            jid = f"{phone[1:]}@s.whatsapp.net"
            db.add(
                AccountContact(
                    account_id=account.id,
                    contact_id=jid,
                    jid=jid,
                    lid=f"dev-{index:03d}@lid" if index % 3 == 0 else None,
                    phone_e164=phone,
                    saved_name=f"演示好友 {index:02d}" if saved else None,
                    notify_name=f"WhatsApp 用户 {index:02d}",
                    verified_name=(
                        f"演示商家 {index:02d}" if index % 7 == 0 else None
                    ),
                    source_mask=(1 if saved else 0) | (2 if contacted else 0),
                    is_saved_contact=saved,
                    has_chat_history=contacted,
                    last_interaction_at=(
                        now - timedelta(days=index) if contacted else None
                    ),
                    active=True,
                    synced_at=now,
                )
            )

        group_names = (
            "北美客户交流群",
            "产品内测群",
            "渠道合作群",
            "VIP 售后群",
            "社区公告群",
            "内容运营群",
            "本地活动群",
            "跨境业务群",
        )
        for index, name in enumerate(group_names, start=1):
            db.add(
                AccountWhatsappGroup(
                    account_id=account.id,
                    group_jid=f"120363000000{index:03d}@g.us",
                    subject=name,
                    size=18 + index * 7,
                    announce=index == 5,
                    restrict=index in {3, 5},
                    community_type=(
                        "community_announcement" if index == 5 else "group"
                    ),
                    addressing_mode="pn",
                    own_role=(
                        "superadmin" if index == 1 else "admin" if index <= 4 else "member"
                    ),
                    can_send=index != 5,
                    active=True,
                    synced_at=now,
                )
            )

        existing_lifecycle = db.scalar(
            select(AccountLifecycleEvent.id).where(
                AccountLifecycleEvent.account_id == account.id
            )
        )
        if existing_lifecycle is None:
            for offset, from_state, to_state, reason in (
                (3, None, "validating", "session_imported"),
                (2, "validating", "linked_offline", "session_verified"),
                (1, "linked_offline", "online_idle", "connected"),
                (0, "online_idle", "linked_offline", "manual_disconnect"),
            ):
                db.add(
                    AccountLifecycleEvent(
                        public_id=new_public_id("ale"),
                        account_id=account.id,
                        from_state=from_state,
                        to_state=to_state,
                        reason_category=reason,
                        occurred_at=now - timedelta(days=offset),
                    )
                )

        db.commit()

        client = WaGatewayClient()
        try:
            gateway_account = client.get(account.gateway_account_id)
        except GatewayError as exc:
            if exc.status_code != 404:
                raise
            gateway_account = client.ensure(
                account.gateway_account_id,
                DEMO_PHONE,
                None,
                protocol_definition_id=str(protocol.protocol_definition_id),
                protocol_version=protocol.protocol_definition.version,
                connection_policy=protocol.connection_policy,
                idle_disconnect_seconds=protocol.idle_disconnect_seconds,
                post_verify_grace_seconds=protocol.post_verify_grace_seconds,
                sync_policy=normalized_sync_policy(protocol.sync_policy_json),
            )
        if gateway_account.get("state") == "unpaired":
            client.pair(account.gateway_account_id, DEMO_PHONE)
            for _ in range(20):
                time.sleep(0.05)
                gateway_account = client.get(account.gateway_account_id)
                if gateway_account.get("state") in {"online_idle", "sending"}:
                    break
        if gateway_account.get("state") in {"online_idle", "sending"}:
            client.sync_metadata(
                account.gateway_account_id,
                {
                    "closeOnline": True,
                    "avatar": False,
                    "groupDetails": False,
                    "contacts": False,
                },
            )
            client.disconnect(account.gateway_account_id)

        db.expire_all()
        refreshed = db.get(PersonalAccount, account.id)
        if refreshed is not None:
            refreshed.status = "linked_offline"
            refreshed.validation_status = "ready"
            refreshed.metadata_sync_status = "ready"
            refreshed.last_error = None
            db.commit()
        return str(account.id)


if __name__ == "__main__":
    account_id = seed()
    print(f"seeded account resource demo: {account_id}")
