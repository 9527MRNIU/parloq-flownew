import {
  legacyReadKey as entityLegacyReadKey,
  snowflakeId,
} from "./entity-identifiers";

type ApiRow = Record<string, unknown>;

export { snowflakeId } from "./entity-identifiers";

export function legacyReadKey(row: ApiRow, prefix: string): string {
  return entityLegacyReadKey(
    row,
    prefix,
    "publicId",
    "public_id",
    "gatewayAccountId",
    "gateway_account_id",
  );
}

export function accountRowKey(row: ApiRow, id: string): string {
  if (id) return `account:${id}`;
  return (
    legacyReadKey(row, "account") ||
    `account:read-only:${String(row.phone || row.phoneNumber || row.phone_number || "unknown")}:${String(row.createdAt || row.created_at || "")}`
  );
}

export function groupRowKey(row: ApiRow, id: string): string {
  if (id) return `account-group:${id}`;
  return (
    legacyReadKey(row, "account-group") ||
    `account-group:read-only:${String(row.name || "unknown")}:${String(row.createdAt || row.created_at || "")}`
  );
}
