from __future__ import annotations

import base64
import hashlib
import io
import json
from datetime import UTC, datetime
from zipfile import ZipFile

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import AccountContact, AccountWhatsappGroup, PersonalAccount
from app.routers.personal_accounts import _apply_gateway_account
from app.services.baileys_credentials import (
    MAX_SESSION_KEY_BYTES,
    MAX_SESSION_KEYS,
    BaileysCredentialError,
    validate_baileys_credentials,
    validate_baileys_session,
)
from app.services.account_avatars import apply_gateway_avatar
from app.services.account_metadata_sync import _apply_gateway_metadata
from app.services.wa_gateway import WaGatewayClient


def _b64(size: int) -> str:
    return base64.b64encode(bytes([7]) * size).decode()


def _buffer(size: int) -> dict:
    return {"type": "Buffer", "data": _b64(size)}


def _credentials(phone: str = "12025550991") -> dict:
    return {
        "Phone": phone,
        "registrationId": 12345,
        "advSecretKey": _b64(32),
        "noiseKey": {"private": _buffer(32), "public": _buffer(32)},
        "signedIdentityKey": {"private": _buffer(32), "public": _buffer(32)},
        "pairingEphemeralKeyPair": {
            "private": _buffer(32),
            "public": _buffer(32),
        },
        "signedPreKey": {
            "keyId": 1,
            "keyPair": {"private": _buffer(32), "public": _buffer(32)},
            "signature": _b64(64),
        },
        "account": {
            "accountSignatureKey": _b64(32),
            "accountSignature": _b64(64),
            "deviceSignature": _b64(64),
            "details": _b64(12),
        },
        "me": {"id": f"{phone}:1@s.whatsapp.net", "name": "Imported Account"},
        "signalIdentities": [
            {
                "identifier": {
                    "name": f"{phone}:1@s.whatsapp.net",
                    "deviceId": 0,
                },
                "identifierKey": _buffer(32),
            }
        ],
        "registered": True,
        "nextPreKeyId": 2,
        "firstUnuploadedPreKeyId": 2,
        "accountSyncCounter": 0,
    }


def _session_bundle(phone: str = "12025550992") -> dict:
    return {
        "format": "parloq-baileys-session",
        "version": 1,
        "library": {"name": "@whiskeysockets/baileys", "version": "7.0.0-rc14"},
        "exportedAt": "2026-08-12T10:00:00.000Z",
        "auth": {
            "creds": _credentials(phone),
            "keys": [
                {
                    "type": "pre-key",
                    "id": "1",
                    "value": {"private": _buffer(32), "public": _buffer(32)},
                },
                {
                    "type": "lid-mapping",
                    "id": f"{phone}@s.whatsapp.net",
                    "value": f"{phone}@lid",
                },
            ],
        },
    }


def test_baileys_validator_checks_shape_lengths_and_phone_match() -> None:
    validated = validate_baileys_credentials(_credentials())
    assert validated.phone_e164 == "+12025550991"
    invalid = _credentials()
    invalid["noiseKey"]["private"] = _buffer(31)
    try:
        validate_baileys_credentials(invalid)
    except BaileysCredentialError as exc:
        assert "noiseKey.private" in str(exc)
    else:
        raise AssertionError("invalid private key length was accepted")

    mismatch = _credentials()
    mismatch["Phone"] = "12025550992"
    try:
        validate_baileys_credentials(mismatch)
    except BaileysCredentialError as exc:
        assert "不一致" in str(exc)
    else:
        raise AssertionError("mismatched Phone and me.id were accepted")


def test_native_bundle_validator_limits_keys_and_entry_size() -> None:
    validated = validate_baileys_session(_session_bundle())
    assert validated.phone_e164 == "+12025550992"
    assert validated.import_format == "parloq_baileys_session_v1"
    assert validated.value["auth"]["keys"][0]["type"] == "pre-key"

    too_many = _session_bundle("12025550993")
    too_many["auth"]["keys"] = [
        {"type": "session", "id": str(index), "value": {"v": 1}}
        for index in range(MAX_SESSION_KEYS + 1)
    ]
    try:
        validate_baileys_session(too_many)
    except BaileysCredentialError as exc:
        assert "密钥数量" in str(exc)
    else:
        raise AssertionError("excessive session key count was accepted")

    oversized = _session_bundle("12025550994")
    oversized["auth"]["keys"] = [
        {
            "type": "session",
            "id": "oversized",
            "value": "x" * (MAX_SESSION_KEY_BYTES + 1),
        }
    ]
    try:
        validate_baileys_session(oversized)
    except BaileysCredentialError as exc:
        assert "256KB" in str(exc)
    else:
        raise AssertionError("oversized session key entry was accepted")


def test_offline_import_is_not_ready_until_gateway_verifies_session() -> None:
    item = PersonalAccount(
        public_id="wa_pending",
        name="Pending import",
        phone_e164="+12025550998",
        status="validating",
        validation_status="validating",
        metadata_sync_status="pending",
        enabled=True,
        created_by=1,
    )
    _apply_gateway_account(
        item,
        {
            "state": "linked_offline",
            "sessionStatus": "pending_verification",
            "quality": {
                "hasAvatar": None,
                "groupCount": None,
                "friendCount": None,
                "mutualContactCount": None,
            },
        },
    )
    assert item.validation_status == "validating"
    assert item.quality_synced_at is None

    _apply_gateway_account(
        item,
        {"state": "linked_offline", "sessionStatus": "verified"},
    )
    assert item.validation_status == "ready"


def test_unknown_gateway_platform_does_not_replace_known_intake_profile() -> None:
    item = PersonalAccount(
        public_id="wa_platform_fallback",
        name="Known intake profile",
        phone_e164="+12025550995",
        status="linked_offline",
        validation_status="ready",
        metadata_sync_status="ready",
        account_type="business",
        device_os="android",
        wa_platform_raw="smba",
        enabled=True,
        created_by=1,
    )
    _apply_gateway_account(
        item,
        {
            "metadata": {
                "accountProfile": {
                    "platformRaw": None,
                    "accountType": "unknown",
                    "deviceOs": "unknown",
                }
            }
        },
    )
    assert item.account_type == "business"
    assert item.device_os == "android"
    assert item.wa_platform_raw == "smba"


def test_gateway_avatar_payload_is_validated_cached_and_clearable() -> None:
    item = PersonalAccount(
        public_id="wa_avatar",
        name="Avatar account",
        phone_e164="+12025550997",
        status="linked_offline",
        validation_status="ready",
        metadata_sync_status="ready",
        enabled=True,
        created_by=1,
    )
    content = b"\x89PNG\r\n\x1a\ncache"
    digest = hashlib.sha256(content).hexdigest()

    assert apply_gateway_avatar(
        item,
        {
            "avatar": {
                "sourceUrl": "https://pps.whatsapp.net/avatar.png",
                "contentType": "image/png",
                "size": len(content),
                "sha256": digest,
                "dataBase64": base64.b64encode(content).decode(),
            }
        },
    )
    assert item.avatar_content == content
    assert item.avatar_sha256 == digest
    assert item.avatar_fetched_at is not None

    assert apply_gateway_avatar(item, {"avatar": None})
    assert item.avatar_source_url is None
    assert item.avatar_content is None


def test_account_resources_are_upserted_scored_and_exposed(
    admin_client: TestClient,
) -> None:
    group = admin_client.post(
        "/api/account-groups",
        json={"name": "Account resource synchronization"},
    ).json()["data"]["group"]
    protocol_id = next(
        row["id"]
        for row in admin_client.get(
            "/api/personal-accounts/import-options"
        ).json()["data"]["rows"]
        if row["available"]
    )
    imported = admin_client.post(
        "/api/personal-accounts/import",
        data={
            "groupId": group["id"],
            "protocolId": protocol_id,
            "name": "Resource model demo",
        },
        files={
            "file": (
                "resource-model.json",
                io.BytesIO(json.dumps(_credentials("12025550996")).encode()),
                "application/json",
            )
        },
    )
    assert imported.status_code == 201, imported.text
    account_id = imported.json()["data"]["account"]["id"]
    synced_at = datetime.now(UTC).isoformat()

    with SessionLocal() as db:
        item = db.get(PersonalAccount, int(account_id))
        assert item is not None
        item.validation_status = "ready"
        item.status = "linked_offline"
        _apply_gateway_metadata(
            db,
            item,
            {
                "metadataSyncStatus": "ready",
                "quality": {"hasAvatar": True},
                "resources": {
                    "contacts": [
                        {
                            "contactId": "12025550101@s.whatsapp.net",
                            "jid": "12025550101@s.whatsapp.net",
                            "phoneE164": "+12025550101",
                            "savedName": "Saved only",
                            "isSavedContact": True,
                            "hasChatHistory": False,
                            "sourceMask": 1,
                        },
                        {
                            "contactId": "12025550102@s.whatsapp.net",
                            "jid": "12025550102@s.whatsapp.net",
                            "phoneE164": "+12025550102",
                            "notifyName": "Contacted only",
                            "isSavedContact": False,
                            "hasChatHistory": True,
                            "sourceMask": 2,
                            "lastInteractionAt": synced_at,
                        },
                        {
                            "contactId": "12025550103@s.whatsapp.net",
                            "jid": "12025550103@s.whatsapp.net",
                            "phoneE164": "+12025550103",
                            "savedName": "Saved and contacted",
                            "isSavedContact": True,
                            "hasChatHistory": True,
                            "sourceMask": 3,
                            "lastInteractionAt": synced_at,
                        },
                    ],
                    "contactsStatus": "complete",
                    "contactsComplete": True,
                    "groups": [
                        {
                            "groupJid": "120363001@g.us",
                            "subject": "First group",
                            "size": 8,
                            "communityType": "group",
                            "ownRole": "admin",
                            "canSend": True,
                            "lastInteractionAt": synced_at,
                        },
                        {
                            "groupJid": "120363002@g.us",
                            "subject": "Second group",
                            "size": 9,
                            "communityType": "group",
                            "ownRole": "member",
                            "canSend": False,
                            "announce": True,
                        },
                        {
                            "groupJid": "120363003@g.us",
                            "subject": "Third group",
                            "size": 5,
                            "communityType": "group",
                            "ownRole": "member",
                            "canSend": True,
                        },
                        {
                            "groupJid": "120363004@g.us",
                            "subject": "Fourth group",
                            "size": 4,
                            "communityType": "group",
                            "ownRole": "superadmin",
                            "canSend": True,
                        },
                    ],
                    "groupsStatus": "complete",
                    "uniqueGroupMemberCount": 11,
                    "identityMappingComplete": True,
                    "platformRaw": "smbi",
                    "accountType": "business",
                    "deviceOs": "ios",
                    "syncedAt": synced_at,
                },
            },
            sync_policy_version=4,
        )
        db.commit()
        assert db.query(AccountContact).filter_by(account_id=item.id, active=True).count() == 3
        assert db.query(AccountWhatsappGroup).filter_by(account_id=item.id, active=True).count() == 4

    account = admin_client.get(f"/api/personal-accounts/{account_id}")
    assert account.status_code == 200, account.text
    body = account.json()["data"]["account"]
    assert body["accountType"] == "business"
    assert body["deviceOs"] == "ios"
    assert body["quality"]["friendCount"] == 3
    assert body["quality"]["groupCount"] == 4
    assert body["quality"]["uniqueGroupMemberCount"] == 11
    assert body["quality"]["score"] == 17
    assert "avatarPoints" not in body["quality"]
    assert body["quality"]["savedContactCount"] == 2
    assert body["quality"]["savedOnlyContactCount"] == 1
    assert body["quality"]["chatHistoryContactCount"] == 2
    assert body["quality"]["savedContactPoints"] == 0.5
    assert body["quality"]["chatHistoryPoints"] == 2
    assert body["quality"]["friendPoints"] == 2.5
    assert body["quality"]["adminGroupMemberPoints"] == 12
    assert body["quality"]["memberGroupMemberPoints"] == 2.5
    assert body["quality"]["groupMemberPoints"] == 14.5

    friends = admin_client.get(
        f"/api/personal-accounts/{account_id}/resources/contacts",
        params={"source": "contacted", "sortBy": "phone", "sortOrder": "asc"},
    )
    assert friends.status_code == 200, friends.text
    assert friends.json()["data"]["total"] == 2
    assert [row["phone"] for row in friends.json()["data"]["rows"]] == [
        "+12025550102",
        "+12025550103",
    ]
    groups = admin_client.get(
        f"/api/personal-accounts/{account_id}/resources/groups",
        params={
            "canSend": "true",
            "communityType": "group",
            "sortBy": "size",
            "sortOrder": "desc",
        },
    )
    assert groups.status_code == 200, groups.text
    assert groups.json()["data"]["total"] == 3
    assert [row["size"] for row in groups.json()["data"]["rows"]] == [8, 5, 4]
    assert groups.json()["data"]["rows"][0]["subject"] == "First group"
    returned_interaction = datetime.fromisoformat(
        groups.json()["data"]["rows"][0]["lastInteractionAt"]
    )
    if returned_interaction.tzinfo is None:
        returned_interaction = returned_interaction.replace(tzinfo=UTC)
    assert returned_interaction == datetime.fromisoformat(synced_at)
    sorted_accounts = admin_client.get(
        "/api/personal-accounts",
        params={
            "accountType": "business",
            "deviceOs": "ios",
            "sortBy": "qualityScore",
            "sortOrder": "desc",
        },
    )
    assert sorted_accounts.status_code == 200, sorted_accounts.text
    assert sorted_accounts.json()["data"]["rows"][0]["id"] == account_id
    sorted_groups = admin_client.get(
        "/api/account-groups",
        params={"sortBy": "averageScore", "sortOrder": "desc"},
    )
    assert sorted_groups.status_code == 200, sorted_groups.text
    matched_group = next(
        row
        for row in sorted_groups.json()["data"]["rows"]
        if row["id"] == group["id"]
    )
    assert matched_group["averageScore"] == 17
    assert matched_group["updatedAt"]
    deleted = admin_client.delete(f"/api/personal-accounts/{account_id}")
    assert deleted.status_code == 200, deleted.text


def test_import_group_statistics_and_export(
    admin_client: TestClient, monkeypatch
) -> None:
    created_group = admin_client.post(
        "/api/account-groups",
        json={"name": "Imported accounts", "description": "JSON imports"},
    )
    assert created_group.status_code == 201, created_group.text
    group_id = created_group.json()["data"]["group"]["id"]
    assert group_id.isdigit()
    assert "publicId" not in created_group.json()["data"]["group"]
    import_options = admin_client.get("/api/personal-accounts/import-options")
    assert import_options.status_code == 200, import_options.text
    available_protocols = [
        row
        for row in import_options.json()["data"]["rows"]
        if row["available"]
    ]
    assert available_protocols
    protocol_id = available_protocols[0]["id"]
    assert available_protocols[0]["type"] == "baileys"
    assert available_protocols[0]["supportedFormats"] == [
        "baileys_creds_json",
        "parloq_baileys_session_v1",
    ]

    payload = json.dumps(_credentials()).encode()
    missing_assignments = admin_client.post(
        "/api/personal-accounts/import",
        files={"file": ("account.json", io.BytesIO(payload), "application/json")},
    )
    assert missing_assignments.status_code == 422
    imported = admin_client.post(
        "/api/personal-accounts/import",
        data={
            "groupId": group_id,
            "protocolId": protocol_id,
            "name": "Customer JSON",
        },
        files={"file": ("account.json", io.BytesIO(payload), "application/json")},
    )
    assert imported.status_code == 201, imported.text
    account = imported.json()["data"]["account"]
    assert account["id"].isdigit()
    assert "publicId" not in account
    assert "gatewayAccountId" not in account
    assert account["source"] == "json_import"
    assert account["importFormat"] == "baileys_creds_json"
    assert account["countryCode"] == "US"
    assert account["validationStatus"] == "validating"
    assert account["metadataSyncStatus"] == "pending"
    assert account["group"]["id"] == group_id
    assert account["protocol"]["id"] == protocol_id
    assert account["quality"]["score"] is None

    statistics = admin_client.get("/api/personal-accounts/statistics")
    assert statistics.status_code == 200, statistics.text
    quality = statistics.json()["data"]["quality"]
    assert quality["noAvatar"]["rate"] is None
    assert quality["noAvatar"]["unknownCount"] >= 1
    assert quality["score"]["average"] is None
    stats_body = statistics.json()["data"]
    assert stats_body["summary"]["totalAccounts"] >= 1
    stats_account = next(row for row in stats_body["rows"] if row["accountId"] == account["id"])
    assert stats_account["hasAvatar"] is None
    assert stats_account["groupCount"] is None
    assert stats_account["syncStatus"] == "pending"

    with SessionLocal() as db:
        stored = db.scalar(
            select(PersonalAccount).where(PersonalAccount.id == int(account["id"]))
        )
        assert stored is not None
        stored.validation_status = "ready"
        stored.metadata_sync_status = "ready"
        stored.status = "linked_offline"
        stored.has_avatar = True
        avatar_content = b"\xff\xd8\xff\xe0"
        stored.avatar_source_url = "https://pps.whatsapp.net/avatar.jpg"
        stored.avatar_content_type = "image/jpeg"
        stored.avatar_size = len(avatar_content)
        stored.avatar_sha256 = hashlib.sha256(avatar_content).hexdigest()
        stored.avatar_content = avatar_content
        stored.avatar_fetched_at = datetime.now(UTC)
        stored.group_count = 3
        stored.friend_count = 12
        stored.unique_group_member_count = 18
        db.commit()

    filtered = admin_client.get(
        "/api/personal-accounts",
        params={
            "source": "json_import",
            "groupId": group_id,
            "protocolId": protocol_id,
            "qualityKnown": "true",
            "status": "offline",
            "pageSize": 1,
        },
    )
    assert filtered.status_code == 200, filtered.text
    filtered_data = filtered.json()["data"]
    assert filtered_data["total"] == 1
    assert filtered_data["rows"][0]["id"] == account["id"]
    assert filtered_data["rows"][0]["quality"]["groupCount"] == 3
    assert filtered_data["rows"][0]["quality"]["avatarUrl"].startswith(
        f"/api/personal-accounts/{account['id']}/avatar?v="
    )

    avatar = admin_client.get(f"/api/personal-accounts/{account['id']}/avatar")
    assert avatar.status_code == 200, avatar.text
    assert avatar.content == b"\xff\xd8\xff\xe0"
    assert avatar.headers["content-type"] == "image/jpeg"
    assert avatar.headers["cache-control"] == "private, max-age=300"
    assert avatar.headers["x-content-type-options"] == "nosniff"

    invalid_filter = admin_client.get(
        "/api/personal-accounts", params={"status": "not-a-status"}
    )
    assert invalid_filter.status_code == 422

    filter_options = admin_client.get("/api/personal-accounts/filter-options")
    assert filter_options.status_code == 200, filter_options.text
    assert any(
        row["id"] == protocol_id
        for row in filter_options.json()["data"]["protocols"]
    )

    lifecycle = admin_client.get(
        f"/api/personal-accounts/{account['id']}/lifecycle",
        params={
            "fromState": "__initial__",
            "reason": "session_imported",
            "sortBy": "toState",
            "sortOrder": "asc",
        },
    )
    assert lifecycle.status_code == 200, lifecycle.text
    lifecycle_data = lifecycle.json()["data"]
    assert lifecycle_data["total"] >= 1
    assert lifecycle_data["rows"][0]["fromState"] is None
    assert lifecycle_data["rows"][0]["reason"] == "session_imported"
    assert lifecycle_data["rows"][0]["toState"]

    monkeypatch.setattr(
        WaGatewayClient,
        "export_session",
        lambda self, account_id: _credentials(),
    )
    exported = admin_client.get(f"/api/personal-accounts/{account['id']}/export")
    assert exported.status_code == 200, exported.text
    assert exported.headers["cache-control"] == "no-store, private"
    assert "attachment" in exported.headers["content-disposition"]
    assert exported.json()["me"]["id"] == _credentials()["me"]["id"]

    batch_exported = admin_client.post(
        "/api/personal-accounts/export/batch",
        json={"accountIds": [account["id"]], "format": "baileys_creds"},
    )
    assert batch_exported.status_code == 200, batch_exported.text
    assert batch_exported.headers["content-type"] == "application/zip"
    assert batch_exported.headers["cache-control"] == "no-store, private"
    with ZipFile(io.BytesIO(batch_exported.content)) as archive:
        filenames = archive.namelist()
        assert filenames == ["12025550991.json"]
        document = json.loads(archive.read(filenames[0]))
        assert document["me"]["id"] == _credentials()["me"]["id"]

    groups = admin_client.get("/api/account-groups").json()["data"]
    matched = next(row for row in groups["rows"] if row["id"] == group_id)
    assert matched["accountCount"] == 1
    assert matched["validAccountCount"] == 1
    assert matched["validRate"] == 1.0
    assert matched["onlineAccountCount"] == 0
    assert matched["abnormalAccountCount"] == 0
    assert matched["pendingValidationCount"] == 0
    assert matched["profileKnownCount"] == 1
    assert matched["profileCompleteCount"] == 1
    assert matched["profileCompleteRate"] == 1.0
    assert matched["profileUnknownCount"] == 0
    assert matched["noAvatarCount"] == 0
    assert matched["noGroupCount"] == 0
    assert matched["zeroFriendCount"] == 0

    with SessionLocal() as db:
        stored = db.scalar(select(PersonalAccount).where(PersonalAccount.id == int(account["id"])))
        assert stored is not None
        # Credential material is relayed to the gateway and never persisted in
        # the control-plane account row.
        assert "advSecretKey" not in repr(stored.__dict__)


def test_native_bundle_import_export_round_trip(
    admin_client: TestClient, monkeypatch
) -> None:
    bundle = _session_bundle("12025550995")
    relayed: dict = {}
    created_group = admin_client.post(
        "/api/account-groups",
        json={"name": "Native session imports"},
    )
    assert created_group.status_code == 201, created_group.text
    group_id = created_group.json()["data"]["group"]["id"]
    import_options = admin_client.get("/api/personal-accounts/import-options")
    protocol_id = next(
        row["id"]
        for row in import_options.json()["data"]["rows"]
        if row["available"]
    )

    def import_session(
        self,
        account_id,
        session,
        proxy_url,
        *,
        protocol_definition_id,
        protocol_version,
    ):
        relayed["accountId"] = account_id
        relayed["session"] = session
        relayed["proxyUrl"] = proxy_url
        relayed["protocolDefinitionId"] = protocol_definition_id
        relayed["protocolVersion"] = protocol_version
        return {"id": account_id, "state": "validating"}

    monkeypatch.setattr(WaGatewayClient, "import_session", import_session)
    imported = admin_client.post(
        "/api/personal-accounts/import",
        data={"groupId": group_id, "protocolId": protocol_id},
        files={
            "file": (
                "native-session.json",
                io.BytesIO(json.dumps(bundle).encode()),
                "application/json",
            )
        },
    )
    assert imported.status_code == 201, imported.text
    account = imported.json()["data"]["account"]
    assert account["phone"] == "+12025550995"
    assert account["countryCode"] == "US"
    assert account["importFormat"] == "parloq_baileys_session_v1"
    assert account["group"]["id"] == group_id
    assert account["protocol"]["id"] == protocol_id
    assert relayed["session"] == bundle
    assert relayed["accountId"] != account["id"]

    with SessionLocal() as db:
        stored = db.scalar(
            select(PersonalAccount).where(PersonalAccount.id == int(account["id"]))
        )
        assert stored is not None
        stored.validation_status = "ready"
        db.commit()

    monkeypatch.setattr(
        WaGatewayClient,
        "export_session",
        lambda self, account_id: bundle,
    )
    exported = admin_client.get(
        f"/api/personal-accounts/{account['id']}/export?format=native"
    )
    assert exported.status_code == 200, exported.text
    assert exported.json() == bundle
    assert exported.json()["auth"]["keys"] == bundle["auth"]["keys"]

    compatible = admin_client.get(
        f"/api/personal-accounts/{account['id']}/export"
    )
    assert compatible.status_code == 200, compatible.text
    assert compatible.json() == bundle["auth"]["creds"]
    assert compatible.headers["x-parloq-export-format"] == "baileys_creds"
