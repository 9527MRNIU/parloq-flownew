type ApiRow = Record<string, unknown>;

// Internal IDs are signed 64-bit decimal Snowflakes. Keeping this strict
// prevents legacy public IDs and external provider identifiers entering API
// routes or relationship payloads.
const SNOWFLAKE_ID = /^[1-9]\d{12,18}$/;

export function snowflakeId(row: ApiRow, ...keys: string[]): string {
  const candidates = keys.length ? keys : ["id"];
  for (const key of candidates) {
    const value = row[key];
    if (typeof value === "string" && SNOWFLAKE_ID.test(value.trim())) {
      return value.trim();
    }
    // Temporary read compatibility for deployments that still serialize a
    // currently-safe Snowflake as JSON number. New APIs must return strings.
    if (
      typeof value === "number" &&
      Number.isSafeInteger(value) &&
      SNOWFLAKE_ID.test(String(value))
    ) {
      return String(value);
    }
  }
  return "";
}

/**
 * Legacy identifiers may keep an old row renderable during rollout, but the
 * returned value is only suitable for an invisible React key. Never display
 * it or send it to an API.
 */
export function legacyReadKey(
  row: ApiRow,
  prefix: string,
  ...legacyKeys: string[]
): string {
  const candidates = legacyKeys.length
    ? legacyKeys
    : ["publicId", "public_id"];
  for (const key of candidates) {
    const value = row[key];
    if (value != null && String(value)) {
      return `${prefix}:legacy:${String(value)}`;
    }
  }
  return "";
}

export function entityRowKey(
  row: ApiRow,
  id: string,
  prefix: string,
  fingerprint: string,
  ...legacyKeys: string[]
): string {
  if (id) return `${prefix}:${id}`;
  return (
    legacyReadKey(row, prefix, ...legacyKeys) ||
    `${prefix}:read-only:${fingerprint}`
  );
}
