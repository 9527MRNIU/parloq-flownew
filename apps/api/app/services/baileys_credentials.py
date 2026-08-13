from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from typing import Any

from app.validation import normalize_phone


MAX_CREDENTIAL_BYTES = 1024 * 1024
MAX_SESSION_BYTES = 10 * 1024 * 1024
MAX_SESSION_KEYS = 20_000
MAX_SESSION_KEY_BYTES = 256 * 1024
SESSION_FORMAT = "parloq-baileys-session"
SESSION_VERSION = 1
_SESSION_KEY_TYPES = {
    "pre-key",
    "session",
    "sender-key",
    "sender-key-memory",
    "app-state-sync-key",
    "app-state-sync-version",
    "lid-mapping",
    "device-list",
    "tctoken",
    "identity-key",
}
_JID_PHONE = re.compile(r"^(?P<phone>[1-9]\d{6,14})(?::\d+)?@s\.whatsapp\.net$")


class BaileysCredentialError(ValueError):
    """A safe validation error which never contains credential values."""


@dataclass(frozen=True)
class ValidatedBaileysCredentials:
    value: dict[str, Any]
    phone_e164: str
    display_name: str | None


@dataclass(frozen=True)
class ValidatedBaileysSession:
    value: dict[str, Any]
    credentials: ValidatedBaileysCredentials
    import_format: str

    @property
    def phone_e164(self) -> str:
        return self.credentials.phone_e164

    @property
    def display_name(self) -> str | None:
        return self.credentials.display_name


def _integer(value: Any, path: str, *, minimum: int = 0, maximum: int = 2**32 - 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise BaileysCredentialError(f"{path} 必须是有效整数")
    return value


def _base64_bytes(value: Any, path: str, *, expected: int | None = None) -> bytes:
    encoded = value
    if isinstance(value, dict):
        if value.get("type") != "Buffer" or "data" not in value:
            raise BaileysCredentialError(f"{path} 必须是 Buffer")
        encoded = value["data"]
    if isinstance(encoded, list):
        if any(isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= 255 for item in encoded):
            raise BaileysCredentialError(f"{path} 包含无效字节")
        raw = bytes(encoded)
    elif isinstance(encoded, str):
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise BaileysCredentialError(f"{path} 不是有效 Base64") from exc
    else:
        raise BaileysCredentialError(f"{path} 必须是 Buffer 或 Base64")
    if expected is not None and len(raw) != expected:
        raise BaileysCredentialError(f"{path} 长度必须为 {expected} 字节")
    return raw


def _key_pair(value: Any, path: str) -> None:
    if not isinstance(value, dict):
        raise BaileysCredentialError(f"{path} 必须是密钥对象")
    _base64_bytes(value.get("private"), f"{path}.private", expected=32)
    _base64_bytes(value.get("public"), f"{path}.public", expected=32)


def _phone(value: dict[str, Any]) -> str:
    explicit = value.get("Phone")
    me = value.get("me")
    if not isinstance(me, dict) or not isinstance(me.get("id"), str):
        raise BaileysCredentialError("me.id 缺失或格式错误")
    match = _JID_PHONE.fullmatch(me["id"])
    if match is None:
        raise BaileysCredentialError("me.id 必须是 WhatsApp 手机号 JID")
    jid_phone = normalize_phone(match.group("phone"))
    if explicit not in {None, ""}:
        try:
            explicit_phone = normalize_phone(str(explicit))
        except ValueError as exc:
            raise BaileysCredentialError("Phone 不是有效手机号") from exc
        if explicit_phone != jid_phone:
            raise BaileysCredentialError("Phone 与 me.id 不一致")
    return jid_phone


def validate_baileys_credentials(value: Any) -> ValidatedBaileysCredentials:
    """Validate a Baileys AuthenticationCreds JSON document without retaining secrets."""

    if not isinstance(value, dict):
        raise BaileysCredentialError("导入文件必须是 JSON 对象")
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    except (RecursionError, TypeError, ValueError) as exc:
        raise BaileysCredentialError("导入文件包含无效 JSON 值") from exc
    if len(encoded) > MAX_CREDENTIAL_BYTES:
        raise BaileysCredentialError("导入文件不能超过 1MB")

    _integer(value.get("registrationId"), "registrationId", minimum=1)
    _key_pair(value.get("noiseKey"), "noiseKey")
    _key_pair(value.get("signedIdentityKey"), "signedIdentityKey")
    _key_pair(value.get("pairingEphemeralKeyPair"), "pairingEphemeralKeyPair")
    _base64_bytes(value.get("advSecretKey"), "advSecretKey", expected=32)

    signed_pre_key = value.get("signedPreKey")
    if not isinstance(signed_pre_key, dict):
        raise BaileysCredentialError("signedPreKey 必须是对象")
    _integer(signed_pre_key.get("keyId"), "signedPreKey.keyId")
    _key_pair(signed_pre_key.get("keyPair"), "signedPreKey.keyPair")
    _base64_bytes(signed_pre_key.get("signature"), "signedPreKey.signature", expected=64)

    account = value.get("account")
    if not isinstance(account, dict):
        raise BaileysCredentialError("account 必须是对象")
    _base64_bytes(account.get("accountSignatureKey"), "account.accountSignatureKey", expected=32)
    _base64_bytes(account.get("accountSignature"), "account.accountSignature", expected=64)
    _base64_bytes(account.get("deviceSignature"), "account.deviceSignature", expected=64)
    details = _base64_bytes(account.get("details"), "account.details")
    if not 1 <= len(details) <= 4096:
        raise BaileysCredentialError("account.details 长度无效")

    if value.get("registered") is not True:
        raise BaileysCredentialError("只允许导入已注册的 Baileys 凭据")
    for key in ("nextPreKeyId", "firstUnuploadedPreKeyId", "accountSyncCounter"):
        _integer(value.get(key), key)

    identities = value.get("signalIdentities")
    if not isinstance(identities, list) or not identities:
        raise BaileysCredentialError("signalIdentities 不能为空")
    if len(identities) > 100:
        raise BaileysCredentialError("signalIdentities 数量异常")
    for index, identity in enumerate(identities):
        path = f"signalIdentities[{index}]"
        if not isinstance(identity, dict) or not isinstance(identity.get("identifier"), dict):
            raise BaileysCredentialError(f"{path} 格式错误")
        identifier = identity["identifier"]
        if not isinstance(identifier.get("name"), str) or not identifier["name"]:
            raise BaileysCredentialError(f"{path}.identifier.name 格式错误")
        _integer(identifier.get("deviceId"), f"{path}.identifier.deviceId")
        _base64_bytes(identity.get("identifierKey"), f"{path}.identifierKey", expected=32)

    me = value["me"]
    display_name = me.get("name")
    if display_name is not None and (not isinstance(display_name, str) or len(display_name) > 120):
        raise BaileysCredentialError("me.name 格式错误")
    return ValidatedBaileysCredentials(
        value=value,
        phone_e164=_phone(value),
        display_name=display_name or None,
    )


def _json_size(value: Any, error: str) -> int:
    try:
        return len(
            json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        )
    except (RecursionError, TypeError, ValueError) as exc:
        raise BaileysCredentialError(error) from exc


def validate_baileys_session(value: Any) -> ValidatedBaileysSession:
    """Validate raw Baileys creds or a complete native Parloq session bundle.

    The returned ``value`` is the original document, so a complete bundle can
    be relayed without dropping its Signal key store.
    """

    if not isinstance(value, dict):
        raise BaileysCredentialError("导入文件必须是 JSON 对象")
    if _json_size(value, "导入文件包含无效 JSON 值") > MAX_SESSION_BYTES:
        raise BaileysCredentialError("导入文件不能超过 10MB")

    if "format" in value and value.get("format") != SESSION_FORMAT:
        raise BaileysCredentialError("不支持的账号导入格式")
    if value.get("format") != SESSION_FORMAT:
        credentials = validate_baileys_credentials(value)
        return ValidatedBaileysSession(
            value=value,
            credentials=credentials,
            import_format="baileys_creds_json",
        )

    if value.get("version") != SESSION_VERSION:
        raise BaileysCredentialError("不支持的 Parloq Baileys 会话包版本")
    library = value.get("library")
    if (
        not isinstance(library, dict)
        or library.get("name") != "@whiskeysockets/baileys"
        or not isinstance(library.get("version"), str)
        or not 1 <= len(library["version"]) <= 64
    ):
        raise BaileysCredentialError("会话包 library 信息无效")
    exported_at = value.get("exportedAt")
    if exported_at is not None and (
        not isinstance(exported_at, str) or not 1 <= len(exported_at) <= 64
    ):
        raise BaileysCredentialError("会话包 exportedAt 无效")

    auth = value.get("auth")
    if not isinstance(auth, dict):
        raise BaileysCredentialError("会话包 auth 必须是对象")
    credentials = validate_baileys_credentials(auth.get("creds"))
    keys = auth.get("keys")
    if not isinstance(keys, list):
        raise BaileysCredentialError("会话包 auth.keys 必须是数组")
    if len(keys) > MAX_SESSION_KEYS:
        raise BaileysCredentialError(f"会话包密钥数量不能超过 {MAX_SESSION_KEYS}")

    seen: set[tuple[str, str]] = set()
    for index, entry in enumerate(keys):
        path = f"auth.keys[{index}]"
        if not isinstance(entry, dict):
            raise BaileysCredentialError(f"{path} 必须是对象")
        key_type = entry.get("type")
        key_id = entry.get("id")
        if key_type not in _SESSION_KEY_TYPES:
            raise BaileysCredentialError(f"{path}.type 不受支持")
        if (
            not isinstance(key_id, str)
            or not 1 <= len(key_id) <= 512
            or any(ord(character) < 32 for character in key_id)
        ):
            raise BaileysCredentialError(f"{path}.id 格式错误")
        if "value" not in entry or entry["value"] is None:
            raise BaileysCredentialError(f"{path}.value 不能为空")
        if (
            _json_size(entry["value"], f"{path}.value 包含无效 JSON 值")
            > MAX_SESSION_KEY_BYTES
        ):
            raise BaileysCredentialError(
                f"{path}.value 不能超过 {MAX_SESSION_KEY_BYTES // 1024}KB"
            )
        identity = (key_type, key_id)
        if identity in seen:
            raise BaileysCredentialError(f"{path} 与其他密钥重复")
        seen.add(identity)

    return ValidatedBaileysSession(
        value=value,
        credentials=credentials,
        import_format="parloq_baileys_session_v1",
    )
