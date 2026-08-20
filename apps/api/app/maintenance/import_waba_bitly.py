from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import sys
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import BitlyProviderAccount
from app.security import encrypt_secret, secret_fingerprint
from app.services.bitly import BitlyClient, BitlyServiceError
from app.snowflake import new_public_id


class BitlyImportError(RuntimeError):
    pass


def _domain(value: object) -> str:
    domain = str(value or "").lower().strip().rstrip(".")
    if not domain or "/" in domain or " " in domain or len(domain) > 255:
        raise BitlyImportError("Bitly returned an invalid short domain")
    return domain


def _unique_name(value: object, taken: set[str]) -> str:
    base = str(value or "").strip()[:120] or "Bitly 账号"
    candidate = base
    suffix = 2
    while candidate in taken:
        marker = f" ({suffix})"
        candidate = f"{base[: 120 - len(marker)]}{marker}"
        suffix += 1
    taken.add(candidate)
    return candidate


def import_accounts(db: Session, payload: Mapping[str, Any]) -> dict[str, int]:
    records = payload.get("accounts")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise BitlyImportError("Bitly import payload must contain an account list")

    existing_fingerprints = set(
        db.scalars(select(BitlyProviderAccount.token_fingerprint)).all()
    )
    taken_names = set(db.scalars(select(BitlyProviderAccount.name)).all())
    source = 0
    imported = 0
    skipped = 0

    try:
        for position, record in enumerate(records, start=1):
            if not isinstance(record, Mapping):
                raise BitlyImportError(f"Bitly account {position} has an invalid shape")
            access_token = record.get("accessToken")
            if not isinstance(access_token, str) or not access_token.strip():
                raise BitlyImportError(f"Bitly account {position} has no access token")
            token = access_token.strip()
            if len(token) > 4096:
                raise BitlyImportError(f"Bitly account {position} has an invalid token")
            source += 1
            fingerprint = secret_fingerprint(token)
            if fingerprint in existing_fingerprints:
                skipped += 1
                continue

            try:
                discovered = BitlyClient(token, is_mock=False).discover_account()
            except BitlyServiceError as exc:
                raise BitlyImportError(
                    f"Bitly account {position} could not be verified"
                ) from exc
            group_guid = str(discovered.get("groupGuid") or "").strip()
            if not group_guid or len(group_guid) > 80:
                raise BitlyImportError(
                    f"Bitly account {position} returned an invalid group"
                )
            db.add(
                BitlyProviderAccount(
                    public_id=new_public_id("bitly"),
                    name=_unique_name(discovered.get("name"), taken_names),
                    token_ciphertext=encrypt_secret(token),
                    token_fingerprint=fingerprint,
                    token_last4=token[-4:],
                    group_guid=group_guid,
                    short_domain=_domain(discovered.get("shortDomain")),
                    enabled=True,
                    status="active",
                    is_mock=False,
                    last_error=None,
                )
            )
            existing_fingerprints.add(fingerprint)
            imported += 1
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {"source": source, "imported": imported, "skipped": skipped}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise BitlyImportError("Bitly import payload must be an object")
        with SessionLocal() as db:
            result = import_accounts(db, payload)
    except Exception:
        print(json.dumps({"status": "failed", "error": "Bitly credential import failed"}))
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
