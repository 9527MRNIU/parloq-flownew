from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    AccountContact,
    AccountMetadataSyncJob,
    AccountWhatsappGroup,
    HyperlinkTaskDelivery,
    MessageDelivery,
    PersonalAccount,
    ProtocolNode,
)
from app.security import utcnow
from app.services.account_avatars import apply_gateway_avatar
from app.services.protocol_nodes import normalized_sync_policy
from app.services.wa_gateway import GatewayError, WaGatewayClient
from app.snowflake import new_public_id


ACTIVE_JOB_STATUSES = {"pending", "running"}


def _metadata_sync_available_at(
    account: PersonalAccount,
    protocol: ProtocolNode | None,
) -> datetime:
    """Keep newly connected sessions stable before opening metadata history."""

    now = utcnow()
    if account.last_connected_at is None or protocol is None:
        return now
    connected_at = account.last_connected_at
    if connected_at.tzinfo is None:
        connected_at = connected_at.replace(tzinfo=UTC)
    grace_seconds = max(0, int(protocol.post_verify_grace_seconds or 0))
    return max(now, connected_at + timedelta(seconds=grace_seconds))


def metadata_sync_job_row(item: AccountMetadataSyncJob) -> dict:
    return {
        "id": str(item.id),
        "accountId": str(item.account_id),
        "protocolId": str(item.protocol_node_id),
        "syncPolicyVersion": item.sync_policy_version,
        "syncPolicy": item.sync_policy_json,
        "status": item.status,
        "attemptCount": item.attempt_count,
        "availableAt": item.available_at.isoformat() if item.available_at else None,
        "startedAt": item.started_at.isoformat() if item.started_at else None,
        "completedAt": item.completed_at.isoformat() if item.completed_at else None,
        "lastError": item.last_error,
        "createdAt": item.created_at.isoformat() if item.created_at else None,
        "updatedAt": item.updated_at.isoformat() if item.updated_at else None,
    }


def enqueue_account_metadata_sync(
    db: Session,
    account: PersonalAccount,
    *,
    sync_policy: dict | None = None,
    sync_policy_version: int | None = None,
) -> AccountMetadataSyncJob:
    """Create one durable metadata job, deduplicated per active account run."""

    active_key = f"account:{account.id}"
    existing = db.scalar(
        select(AccountMetadataSyncJob).where(
            AccountMetadataSyncJob.active_key == active_key,
            AccountMetadataSyncJob.status.in_(ACTIVE_JOB_STATUSES),
        )
    )
    protocol = db.get(ProtocolNode, account.protocol_id)
    policy = normalized_sync_policy(
        sync_policy
        if isinstance(sync_policy, dict)
        else protocol.sync_policy_json if protocol is not None else None
    )
    version = (
        sync_policy_version
        if sync_policy_version is not None
        else protocol.sync_policy_version if protocol is not None else 1
    )
    available_at = _metadata_sync_available_at(account, protocol)
    if existing is not None:
        if existing.status == "pending":
            existing.sync_policy_json = policy
            existing.sync_policy_version = version
            current_available_at = existing.available_at
            if current_available_at.tzinfo is None:
                current_available_at = current_available_at.replace(tzinfo=UTC)
            existing.available_at = max(current_available_at, available_at)
            account.metadata_sync_status = "pending"
        return existing
    item = AccountMetadataSyncJob(
        public_id=new_public_id("amsync"),
        account_id=account.id,
        protocol_node_id=account.protocol_id,
        sync_policy_version=version,
        sync_policy_json=policy,
        status="pending",
        active_key=active_key,
        attempt_count=0,
        available_at=available_at,
        result_json={},
        created_by=account.created_by,
    )
    account.metadata_sync_status = "pending"
    try:
        with db.begin_nested():
            db.add(item)
            db.flush()
    except IntegrityError:
        existing = db.scalar(
            select(AccountMetadataSyncJob).where(
                AccountMetadataSyncJob.active_key == active_key,
                AccountMetadataSyncJob.status.in_(ACTIVE_JOB_STATUSES),
            )
        )
        if existing is None:
            raise
        return existing
    return item


def _text(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized[:limit] if normalized else None


def _timestamp(value: object, fallback: datetime) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    return fallback


def _timestamp_seconds(value: datetime) -> float:
    normalized = value if value.tzinfo else value.replace(tzinfo=UTC)
    return normalized.timestamp()


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _apply_contacts(
    db: Session,
    account: PersonalAccount,
    resources: dict,
    synced_at: datetime,
) -> None:
    rows = resources.get("contacts")
    if not isinstance(rows, list):
        rows = []
    incoming_ids: set[str] = set()
    existing = {
        item.contact_id: item
        for item in db.scalars(
            select(AccountContact).where(AccountContact.account_id == account.id)
        ).all()
    }
    for value in rows:
        if not isinstance(value, dict):
            continue
        contact_id = _text(value.get("contactId"), 191)
        if contact_id is None:
            continue
        incoming_ids.add(contact_id)
        item = existing.get(contact_id)
        if item is None:
            item = AccountContact(
                account_id=account.id,
                contact_id=contact_id,
                synced_at=synced_at,
            )
            db.add(item)
            existing[contact_id] = item
        item.jid = _text(value.get("jid"), 191)
        item.lid = _text(value.get("lid"), 191)
        item.phone_e164 = _text(value.get("phoneE164"), 20)
        item.saved_name = _text(value.get("savedName"), 255)
        item.notify_name = _text(value.get("notifyName"), 255)
        item.verified_name = _text(value.get("verifiedName"), 255)
        item.image_state = _text(value.get("imageState"), 255)
        item.profile_status = _text(value.get("profileStatus"), 512)
        item.source_mask = _nonnegative_int(value.get("sourceMask")) or 0
        item.is_saved_contact = value.get("isSavedContact") is True
        item.has_chat_history = value.get("hasChatHistory") is True
        item.last_interaction_at = (
            _timestamp(value.get("lastInteractionAt"), synced_at)
            if value.get("lastInteractionAt")
            else None
        )
        item.active = item.is_saved_contact or item.has_chat_history
        item.synced_at = synced_at

    if resources.get("contactsComplete") is True:
        for contact_id, item in existing.items():
            if contact_id not in incoming_ids:
                item.active = False
                item.synced_at = synced_at
    db.flush()
    account.friend_count = int(
        db.scalar(
            select(func.count())
            .select_from(AccountContact)
            .where(
                AccountContact.account_id == account.id,
                AccountContact.active.is_(True),
                (
                    AccountContact.is_saved_contact.is_(True)
                    | AccountContact.has_chat_history.is_(True)
                ),
            )
        )
        or 0
    )


def _apply_groups(
    db: Session,
    account: PersonalAccount,
    resources: dict,
    synced_at: datetime,
) -> None:
    rows = resources.get("groups")
    if not isinstance(rows, list):
        rows = []
    incoming_ids: set[str] = set()
    existing = {
        item.group_jid: item
        for item in db.scalars(
            select(AccountWhatsappGroup).where(
                AccountWhatsappGroup.account_id == account.id
            )
        ).all()
    }
    for value in rows:
        if not isinstance(value, dict):
            continue
        group_jid = _text(value.get("groupJid"), 191)
        if group_jid is None:
            continue
        incoming_ids.add(group_jid)
        item = existing.get(group_jid)
        if item is None:
            item = AccountWhatsappGroup(
                account_id=account.id,
                group_jid=group_jid,
                synced_at=synced_at,
            )
            db.add(item)
            existing[group_jid] = item
        item.subject = _text(value.get("subject"), 255) or ""
        item.size = _nonnegative_int(value.get("size")) or 0
        item.announce = value.get("announce") is True
        item.restrict = value.get("restrict") is True
        item.community_type = (
            value.get("communityType")
            if value.get("communityType")
            in {"group", "community", "community_announcement"}
            else "group"
        )
        item.addressing_mode = _text(value.get("addressingMode"), 32)
        item.linked_parent_jid = _text(value.get("linkedParentJid"), 191)
        item.own_role = (
            value.get("ownRole")
            if value.get("ownRole") in {"member", "admin", "superadmin"}
            else "member"
        )
        item.can_send = value.get("canSend") is True
        if value.get("lastInteractionAt"):
            interaction_at = _timestamp(
                value.get("lastInteractionAt"), synced_at
            )
            if (
                item.last_interaction_at is None
                or _timestamp_seconds(interaction_at)
                > _timestamp_seconds(item.last_interaction_at)
            ):
                item.last_interaction_at = interaction_at
        item.active = True
        item.synced_at = synced_at

    if resources.get("groupsStatus") == "complete":
        for group_jid, item in existing.items():
            if group_jid not in incoming_ids:
                item.active = False
                item.synced_at = synced_at
    db.flush()
    account.group_count = int(
        db.scalar(
            select(func.count())
            .select_from(AccountWhatsappGroup)
            .where(
                AccountWhatsappGroup.account_id == account.id,
                AccountWhatsappGroup.active.is_(True),
            )
        )
        or 0
    )


def _apply_gateway_metadata(
    db: Session,
    account: PersonalAccount,
    value: dict,
    *,
    sync_policy_version: int | None = None,
) -> None:
    metadata_status = value.get("metadataSyncStatus")
    if metadata_status in {"ready", "unsupported"}:
        account.metadata_sync_status = metadata_status
    else:
        account.metadata_sync_status = "ready"
    quality = value.get("quality")
    quality_known = False
    if isinstance(quality, dict):
        if isinstance(quality.get("hasAvatar"), bool):
            account.has_avatar = quality["hasAvatar"]
            quality_known = True
        for source_key, attribute in (
            ("groupCount", "group_count"),
            ("friendCount", "friend_count"),
        ):
            metric = quality.get(source_key)
            if isinstance(metric, int) and not isinstance(metric, bool) and metric >= 0:
                setattr(account, attribute, metric)
                quality_known = True
    resources = value.get("resources")
    if isinstance(resources, dict):
        synced_at = _timestamp(resources.get("syncedAt"), utcnow())
        contacts_status = resources.get("contactsStatus")
        groups_status = resources.get("groupsStatus")
        if (
            isinstance(resources.get("contacts"), list)
            and contacts_status in {"partial", "complete"}
        ):
            _apply_contacts(db, account, resources, synced_at)
            quality_known = True
        if (
            isinstance(resources.get("groups"), list)
            and groups_status == "complete"
        ):
            _apply_groups(db, account, resources, synced_at)
            quality_known = True
        if groups_status == "complete":
            unique_members = _nonnegative_int(
                resources.get("uniqueGroupMemberCount")
            )
            if unique_members is not None:
                account.unique_group_member_count = unique_members
        platform_raw = _text(resources.get("platformRaw"), 32)
        if platform_raw is not None:
            account.wa_platform_raw = platform_raw
        if resources.get("accountType") in {"personal", "business"}:
            account.account_type = resources["accountType"]
        if resources.get("deviceOs") in {"android", "ios", "other"}:
            account.device_os = resources["deviceOs"]
        account.resource_sync_state_json = {
            "appliedPolicyVersion": sync_policy_version,
            "contacts": {
                "status": resources.get("contactsStatus", "pending"),
                "complete": resources.get("contactsComplete") is True,
                "count": account.friend_count,
                "syncedAt": synced_at.isoformat(),
            },
            "groups": {
                "status": resources.get("groupsStatus", "pending"),
                "identityMappingComplete": (
                    resources.get("identityMappingComplete") is True
                ),
                "count": account.group_count,
                "uniqueMemberCount": account.unique_group_member_count,
                "syncedAt": synced_at.isoformat(),
            },
        }
    if quality_known:
        account.quality_synced_at = utcnow()
    apply_gateway_avatar(account, value)
    account.last_error = None


def _claim_jobs(limit: int) -> list[int]:
    with SessionLocal() as db:
        stale_before = utcnow() - timedelta(minutes=5)
        recent_message_cutoff = utcnow() - timedelta(minutes=10)
        jobs = list(
            db.scalars(
                select(AccountMetadataSyncJob)
                .join(
                    PersonalAccount,
                    PersonalAccount.id == AccountMetadataSyncJob.account_id,
                )
                .where(
                    (
                        (AccountMetadataSyncJob.status == "pending")
                        & (AccountMetadataSyncJob.available_at <= utcnow())
                    )
                    | (
                        (AccountMetadataSyncJob.status == "running")
                        & (AccountMetadataSyncJob.started_at < stale_before)
                    ),
                    PersonalAccount.status.not_in(
                        ("pairing", "warming", "sending", "draining")
                    ),
                    ~select(MessageDelivery.id)
                    .where(
                        MessageDelivery.account_id == PersonalAccount.id,
                        MessageDelivery.status == "queued",
                        MessageDelivery.queued_at >= recent_message_cutoff,
                    )
                    .exists(),
                    ~select(HyperlinkTaskDelivery.id)
                    .where(
                        HyperlinkTaskDelivery.account_id == PersonalAccount.id,
                        HyperlinkTaskDelivery.submission_status.in_(
                            ("leased", "submitting", "reconciling")
                        ),
                    )
                    .exists(),
                )
                .order_by(
                    AccountMetadataSyncJob.available_at,
                    AccountMetadataSyncJob.created_at,
                    AccountMetadataSyncJob.id,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
        )
        now = utcnow()
        for job in jobs:
            job.status = "running"
            job.started_at = now
            job.completed_at = None
            job.last_error = None
            job.attempt_count = int(job.attempt_count or 0) + 1
            account = db.get(PersonalAccount, job.account_id)
            if account is not None and account.deleted_at is None:
                account.metadata_sync_status = "syncing"
        db.commit()
        return [job.id for job in jobs]


def process_pending_account_metadata_sync_jobs(limit: int = 1) -> dict[str, int]:
    """Run pending jobs once; gateway owns only its short in-request retries."""

    job_ids = _claim_jobs(max(1, min(limit, 20)))
    succeeded = 0
    failed = 0
    for job_id in job_ids:
        with SessionLocal() as db:
            job = db.get(AccountMetadataSyncJob, job_id)
            account = db.get(PersonalAccount, job.account_id) if job else None
            if job is None:
                continue
            try:
                if account is None or account.deleted_at is not None:
                    raise GatewayError("账号已不存在")
                if account.admission_status != "active":
                    raise GatewayError("账号尚未正式入池")
                value = WaGatewayClient().sync_metadata(
                    account.gateway_account_id,
                    job.sync_policy_json,
                )
                _apply_gateway_metadata(
                    db,
                    account,
                    value,
                    sync_policy_version=job.sync_policy_version,
                )
                job.status = "succeeded"
                job.result_json = {
                    "metadataSyncStatus": account.metadata_sync_status,
                    "quality": value.get("quality") if isinstance(value, dict) else {},
                    "resourceSync": account.resource_sync_state_json,
                }
                succeeded += 1
            except GatewayError as exc:
                job.status = "failed"
                job.last_error = str(exc)[:2000]
                if account is not None and account.deleted_at is None:
                    account.metadata_sync_status = "failed"
                    account.last_error = str(exc)[:2000]
                failed += 1
            job.completed_at = utcnow()
            job.active_key = None
            db.commit()
    return {"claimed": len(job_ids), "succeeded": succeeded, "failed": failed}
