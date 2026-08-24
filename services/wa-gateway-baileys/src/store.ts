import pg from 'pg'
import type { Account, AccountState, AccountStateTransition, Message, PairingStatus, SessionCompleteness, SessionStatus, StoredAuth, StoredKey } from './domain.js'
import { GatewayError, normalizeSyncPolicy } from './domain.js'
import { nextSnowflakeId } from './snowflake.js'

const { Pool } = pg

export interface Store {
  migrate(): Promise<void>
  ready(): Promise<void>
  close(): Promise<void>
  createAccount(account: Pick<Account, 'id' | 'protocolDefinitionId' | 'protocolVersion' | 'phoneE164' | 'proxyUrl' | 'state' | 'connectionPolicy' | 'idleDisconnectSeconds' | 'postVerifyGraceSeconds' | 'syncPolicy'>): Promise<Account>
  claimUnpairedAccount(account: Pick<Account, 'id' | 'protocolDefinitionId' | 'protocolVersion' | 'phoneE164' | 'proxyUrl' | 'connectionPolicy' | 'idleDisconnectSeconds' | 'postVerifyGraceSeconds' | 'syncPolicy'>): Promise<Account | null>
  createImportedAccount(account: Pick<Account, 'id' | 'protocolDefinitionId' | 'protocolVersion' | 'phoneE164' | 'proxyUrl' | 'state' | 'deviceJid' | 'autoConnect' | 'sessionStatus' | 'sessionCompleteness' | 'connectionPolicy' | 'idleDisconnectSeconds' | 'postVerifyGraceSeconds' | 'syncPolicy'>, auth: StoredAuth): Promise<Account>
  listAccounts(): Promise<Account[]>
  getAccount(id: string): Promise<Account>
  updateAccount(id: string, changes: Partial<Pick<Account, 'phoneE164' | 'proxyUrl' | 'deviceJid' | 'autoConnect' | 'sessionStatus' | 'sessionCompleteness' | 'pairingStatus' | 'pairingExpiresAt' | 'metadataSyncStatus' | 'hasAvatar' | 'groupCount' | 'friendCount' | 'mutualContactCount' | 'connectionPolicy' | 'idleDisconnectSeconds' | 'postVerifyGraceSeconds' | 'syncPolicy' | 'metadata'>>): Promise<Account>
  transitionAccount(id: string, state: AccountState, changes: Partial<Pick<Account, 'deviceJid' | 'autoConnect' | 'sessionStatus' | 'sessionCompleteness' | 'pairingStatus' | 'pairingExpiresAt' | 'metadataSyncStatus'>>, reasonCategory: string, providerCode?: string): Promise<AccountStateTransition>
  createMessage(message: Message): Promise<{ message: Message; created: boolean }>
  getMessage(id: string): Promise<Message>
  updateMessage(id: string, changes: Partial<Pick<Message, 'providerMessageId' | 'status' | 'errorCode' | 'sentAt' | 'deliveredAt'>>): Promise<Message>
  markDeliveredByProvider(accountId: string, providerMessageId: string): Promise<Message | null>
  getCreds(accountId: string): Promise<unknown | null>
  setCreds(accountId: string, creds: unknown): Promise<void>
  getKeys(accountId: string, type: string, ids: string[]): Promise<Record<string, unknown>>
  setKeys(accountId: string, keys: StoredKey[]): Promise<void>
  getAllKeys(accountId: string): Promise<StoredKey[]>
  replaceAuth(accountId: string, auth: StoredAuth): Promise<void>
  clearAuth(accountId: string): Promise<void>
}

const schema = `
CREATE SCHEMA IF NOT EXISTS wa_gateway_baileys;
CREATE TABLE IF NOT EXISTS wa_gateway_baileys.accounts (
  id TEXT PRIMARY KEY,
  protocol_definition_id TEXT NOT NULL DEFAULT '0',
  protocol_version TEXT NOT NULL DEFAULT '6.7.24',
  phone_e164 TEXT NOT NULL UNIQUE,
  proxy_url TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL DEFAULT 'unpaired',
  device_jid TEXT NOT NULL DEFAULT '',
  auto_connect BOOLEAN NOT NULL DEFAULT FALSE,
  connection_policy TEXT NOT NULL DEFAULT 'on_demand',
  idle_disconnect_seconds INTEGER NOT NULL DEFAULT 600,
  post_verify_grace_seconds INTEGER NOT NULL DEFAULT 120,
  sync_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  session_status TEXT NOT NULL DEFAULT 'none',
  session_completeness TEXT NOT NULL DEFAULT 'none',
  pairing_status TEXT NOT NULL DEFAULT 'idle',
  pairing_expires_at TIMESTAMPTZ,
  metadata_sync_status TEXT NOT NULL DEFAULT 'pending',
  has_avatar BOOLEAN,
  group_count INTEGER,
  friend_count INTEGER,
  mutual_contact_count INTEGER,
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  state_changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  invalidated_at TIMESTAMPTZ,
  reason_category TEXT NOT NULL DEFAULT 'created',
  provider_code TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE wa_gateway_baileys.accounts
  ADD COLUMN IF NOT EXISTS metadata_sync_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE wa_gateway_baileys.accounts ADD COLUMN IF NOT EXISTS protocol_definition_id TEXT NOT NULL DEFAULT '0';
ALTER TABLE wa_gateway_baileys.accounts ALTER COLUMN protocol_definition_id SET DEFAULT '0';
UPDATE wa_gateway_baileys.accounts SET protocol_definition_id='0' WHERE protocol_definition_id='builtin';
ALTER TABLE wa_gateway_baileys.accounts ADD COLUMN IF NOT EXISTS protocol_version TEXT NOT NULL DEFAULT '6.7.24';
CREATE INDEX IF NOT EXISTS accounts_protocol_definition_idx ON wa_gateway_baileys.accounts(protocol_definition_id);
ALTER TABLE wa_gateway_baileys.accounts ADD COLUMN IF NOT EXISTS has_avatar BOOLEAN;
ALTER TABLE wa_gateway_baileys.accounts ADD COLUMN IF NOT EXISTS group_count INTEGER;
ALTER TABLE wa_gateway_baileys.accounts ADD COLUMN IF NOT EXISTS friend_count INTEGER;
ALTER TABLE wa_gateway_baileys.accounts ADD COLUMN IF NOT EXISTS mutual_contact_count INTEGER;
ALTER TABLE wa_gateway_baileys.accounts ADD COLUMN IF NOT EXISTS state_changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE wa_gateway_baileys.accounts ADD COLUMN IF NOT EXISTS invalidated_at TIMESTAMPTZ;
ALTER TABLE wa_gateway_baileys.accounts ADD COLUMN IF NOT EXISTS reason_category TEXT NOT NULL DEFAULT 'created';
ALTER TABLE wa_gateway_baileys.accounts ADD COLUMN IF NOT EXISTS provider_code TEXT;
ALTER TABLE wa_gateway_baileys.accounts ADD COLUMN IF NOT EXISTS pairing_status TEXT NOT NULL DEFAULT 'idle';
ALTER TABLE wa_gateway_baileys.accounts ADD COLUMN IF NOT EXISTS pairing_expires_at TIMESTAMPTZ;
ALTER TABLE wa_gateway_baileys.accounts ADD COLUMN IF NOT EXISTS connection_policy TEXT NOT NULL DEFAULT 'on_demand';
ALTER TABLE wa_gateway_baileys.accounts ADD COLUMN IF NOT EXISTS idle_disconnect_seconds INTEGER NOT NULL DEFAULT 600;
ALTER TABLE wa_gateway_baileys.accounts ADD COLUMN IF NOT EXISTS post_verify_grace_seconds INTEGER NOT NULL DEFAULT 120;
ALTER TABLE wa_gateway_baileys.accounts ADD COLUMN IF NOT EXISTS sync_policy JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE wa_gateway_baileys.accounts ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb;
UPDATE wa_gateway_baileys.accounts
  SET sync_policy = sync_policy
      - 'profileStatus' - 'profile_status'
      - 'businessProfile' - 'business_profile'
      - 'privacySettings' - 'privacy_settings'
      - 'blocklist',
      metadata_json = metadata_json
      - 'profileStatus' - 'profileStatusError'
      - 'businessProfile' - 'businessProfileError'
      - 'privacySettings' - 'privacySettingsError'
      - 'blocklist' - 'blocklistError'
  WHERE sync_policy ?| ARRAY[
          'profileStatus', 'profile_status',
          'businessProfile', 'business_profile',
          'privacySettings', 'privacy_settings',
          'blocklist'
        ]
     OR metadata_json ?| ARRAY[
          'profileStatus', 'profileStatusError',
          'businessProfile', 'businessProfileError',
          'privacySettings', 'privacySettingsError',
          'blocklist', 'blocklistError'
        ];
UPDATE wa_gateway_baileys.accounts
  SET invalidated_at=COALESCE(invalidated_at,state_changed_at), reason_category='restricted'
  WHERE state='restricted' AND invalidated_at IS NULL;
CREATE TABLE IF NOT EXISTS wa_gateway_baileys.messages (
  message_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES wa_gateway_baileys.accounts(id) ON DELETE CASCADE,
  recipient_e164 TEXT NOT NULL,
  provider_message_id TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  error_code TEXT NOT NULL DEFAULT '',
  queued_at TIMESTAMPTZ NOT NULL,
  sent_at TIMESTAMPTZ,
  delivered_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS messages_provider_idx
  ON wa_gateway_baileys.messages(account_id, provider_message_id)
  WHERE provider_message_id <> '';
CREATE TABLE IF NOT EXISTS wa_gateway_baileys.auth_creds (
  account_id TEXT PRIMARY KEY REFERENCES wa_gateway_baileys.accounts(id) ON DELETE CASCADE,
  value JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS wa_gateway_baileys.auth_keys (
  account_id TEXT NOT NULL REFERENCES wa_gateway_baileys.accounts(id) ON DELETE CASCADE,
  category TEXT NOT NULL,
  key_id TEXT NOT NULL,
  value JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (account_id, category, key_id)
);
ALTER TABLE wa_gateway_baileys.accounts ADD COLUMN IF NOT EXISTS internal_id BIGINT;
ALTER TABLE wa_gateway_baileys.messages ADD COLUMN IF NOT EXISTS internal_id BIGINT;
ALTER TABLE wa_gateway_baileys.messages ADD COLUMN IF NOT EXISTS account_internal_id BIGINT;
ALTER TABLE wa_gateway_baileys.auth_creds ADD COLUMN IF NOT EXISTS internal_id BIGINT;
ALTER TABLE wa_gateway_baileys.auth_creds ADD COLUMN IF NOT EXISTS account_internal_id BIGINT;
ALTER TABLE wa_gateway_baileys.auth_keys ADD COLUMN IF NOT EXISTS internal_id BIGINT;
ALTER TABLE wa_gateway_baileys.auth_keys ADD COLUMN IF NOT EXISTS account_internal_id BIGINT;

WITH ranked AS (
  SELECT ctid, row_number() OVER (ORDER BY created_at,id) AS rn
  FROM wa_gateway_baileys.accounts WHERE internal_id IS NULL
)
UPDATE wa_gateway_baileys.accounts AS target
SET internal_id = (
  ((GREATEST((EXTRACT(EPOCH FROM clock_timestamp())*1000)::BIGINT,1785542400000)-1785542400000+(ranked.rn-1)/4096) << 22)
  | (1000::BIGINT << 12) | ((ranked.rn-1)%4096)
)
FROM ranked WHERE target.ctid=ranked.ctid;
WITH ranked AS (
  SELECT ctid, row_number() OVER (ORDER BY queued_at,message_id) AS rn
  FROM wa_gateway_baileys.messages WHERE internal_id IS NULL
)
UPDATE wa_gateway_baileys.messages AS target
SET internal_id = (
  ((GREATEST((EXTRACT(EPOCH FROM clock_timestamp())*1000)::BIGINT,1785542400000)-1785542400000+(ranked.rn-1)/4096) << 22)
  | (1001::BIGINT << 12) | ((ranked.rn-1)%4096)
)
FROM ranked WHERE target.ctid=ranked.ctid;
WITH ranked AS (
  SELECT ctid, row_number() OVER (ORDER BY account_id) AS rn
  FROM wa_gateway_baileys.auth_creds WHERE internal_id IS NULL
)
UPDATE wa_gateway_baileys.auth_creds AS target
SET internal_id = (
  ((GREATEST((EXTRACT(EPOCH FROM clock_timestamp())*1000)::BIGINT,1785542400000)-1785542400000+(ranked.rn-1)/4096) << 22)
  | (1002::BIGINT << 12) | ((ranked.rn-1)%4096)
)
FROM ranked WHERE target.ctid=ranked.ctid;
WITH ranked AS (
  SELECT ctid, row_number() OVER (ORDER BY account_id,category,key_id) AS rn
  FROM wa_gateway_baileys.auth_keys WHERE internal_id IS NULL
)
UPDATE wa_gateway_baileys.auth_keys AS target
SET internal_id = (
  ((GREATEST((EXTRACT(EPOCH FROM clock_timestamp())*1000)::BIGINT,1785542400000)-1785542400000+(ranked.rn-1)/4096) << 22)
  | (1003::BIGINT << 12) | ((ranked.rn-1)%4096)
)
FROM ranked WHERE target.ctid=ranked.ctid;

UPDATE wa_gateway_baileys.messages AS child SET account_internal_id=parent.internal_id
FROM wa_gateway_baileys.accounts AS parent
WHERE child.account_id=parent.id AND child.account_internal_id IS NULL;
UPDATE wa_gateway_baileys.auth_creds AS child SET account_internal_id=parent.internal_id
FROM wa_gateway_baileys.accounts AS parent
WHERE child.account_id=parent.id AND child.account_internal_id IS NULL;
UPDATE wa_gateway_baileys.auth_keys AS child SET account_internal_id=parent.internal_id
FROM wa_gateway_baileys.accounts AS parent
WHERE child.account_id=parent.id AND child.account_internal_id IS NULL;

ALTER TABLE wa_gateway_baileys.accounts ALTER COLUMN internal_id SET NOT NULL;
ALTER TABLE wa_gateway_baileys.messages ALTER COLUMN internal_id SET NOT NULL;
ALTER TABLE wa_gateway_baileys.messages ALTER COLUMN account_internal_id SET NOT NULL;
ALTER TABLE wa_gateway_baileys.auth_creds ALTER COLUMN internal_id SET NOT NULL;
ALTER TABLE wa_gateway_baileys.auth_creds ALTER COLUMN account_internal_id SET NOT NULL;
ALTER TABLE wa_gateway_baileys.auth_keys ALTER COLUMN internal_id SET NOT NULL;
ALTER TABLE wa_gateway_baileys.auth_keys ALTER COLUMN account_internal_id SET NOT NULL;

ALTER TABLE wa_gateway_baileys.messages DROP CONSTRAINT IF EXISTS messages_account_id_fkey;
ALTER TABLE wa_gateway_baileys.auth_creds DROP CONSTRAINT IF EXISTS auth_creds_account_id_fkey;
ALTER TABLE wa_gateway_baileys.auth_keys DROP CONSTRAINT IF EXISTS auth_keys_account_id_fkey;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='accounts_id_snowflake_key' AND connamespace='wa_gateway_baileys'::regnamespace) THEN
    ALTER TABLE wa_gateway_baileys.accounts ADD CONSTRAINT accounts_id_snowflake_key UNIQUE(id);
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_constraint c
    JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=ANY(c.conkey)
    WHERE c.conrelid='wa_gateway_baileys.accounts'::regclass AND c.contype='p' AND a.attname='id'
  ) THEN ALTER TABLE wa_gateway_baileys.accounts DROP CONSTRAINT accounts_pkey; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='wa_gateway_baileys.accounts'::regclass AND contype='p') THEN
    ALTER TABLE wa_gateway_baileys.accounts ADD CONSTRAINT accounts_pkey PRIMARY KEY(internal_id);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='messages_message_id_snowflake_key' AND connamespace='wa_gateway_baileys'::regnamespace) THEN
    ALTER TABLE wa_gateway_baileys.messages ADD CONSTRAINT messages_message_id_snowflake_key UNIQUE(message_id);
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_constraint c
    JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=ANY(c.conkey)
    WHERE c.conrelid='wa_gateway_baileys.messages'::regclass AND c.contype='p' AND a.attname='message_id'
  ) THEN ALTER TABLE wa_gateway_baileys.messages DROP CONSTRAINT messages_pkey; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='wa_gateway_baileys.messages'::regclass AND contype='p') THEN
    ALTER TABLE wa_gateway_baileys.messages ADD CONSTRAINT messages_pkey PRIMARY KEY(internal_id);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='auth_creds_account_id_snowflake_key' AND connamespace='wa_gateway_baileys'::regnamespace) THEN
    ALTER TABLE wa_gateway_baileys.auth_creds ADD CONSTRAINT auth_creds_account_id_snowflake_key UNIQUE(account_id);
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_constraint c
    JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=ANY(c.conkey)
    WHERE c.conrelid='wa_gateway_baileys.auth_creds'::regclass AND c.contype='p' AND a.attname='account_id'
  ) THEN ALTER TABLE wa_gateway_baileys.auth_creds DROP CONSTRAINT auth_creds_pkey; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='wa_gateway_baileys.auth_creds'::regclass AND contype='p') THEN
    ALTER TABLE wa_gateway_baileys.auth_creds ADD CONSTRAINT auth_creds_pkey PRIMARY KEY(internal_id);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='auth_keys_lookup_snowflake_key' AND connamespace='wa_gateway_baileys'::regnamespace) THEN
    ALTER TABLE wa_gateway_baileys.auth_keys ADD CONSTRAINT auth_keys_lookup_snowflake_key UNIQUE(account_id,category,key_id);
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_constraint c
    JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=ANY(c.conkey)
    WHERE c.conrelid='wa_gateway_baileys.auth_keys'::regclass AND c.contype='p' AND a.attname='account_id'
  ) THEN ALTER TABLE wa_gateway_baileys.auth_keys DROP CONSTRAINT auth_keys_pkey; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='wa_gateway_baileys.auth_keys'::regclass AND contype='p') THEN
    ALTER TABLE wa_gateway_baileys.auth_keys ADD CONSTRAINT auth_keys_pkey PRIMARY KEY(internal_id);
  END IF;
END $$;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='messages_account_internal_id_fkey' AND connamespace='wa_gateway_baileys'::regnamespace) THEN
    ALTER TABLE wa_gateway_baileys.messages
      ADD CONSTRAINT messages_account_internal_id_fkey FOREIGN KEY(account_internal_id)
      REFERENCES wa_gateway_baileys.accounts(internal_id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='auth_creds_account_internal_id_fkey' AND connamespace='wa_gateway_baileys'::regnamespace) THEN
    ALTER TABLE wa_gateway_baileys.auth_creds
      ADD CONSTRAINT auth_creds_account_internal_id_fkey FOREIGN KEY(account_internal_id)
      REFERENCES wa_gateway_baileys.accounts(internal_id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='auth_keys_account_internal_id_fkey' AND connamespace='wa_gateway_baileys'::regnamespace) THEN
    ALTER TABLE wa_gateway_baileys.auth_keys
      ADD CONSTRAINT auth_keys_account_internal_id_fkey FOREIGN KEY(account_internal_id)
      REFERENCES wa_gateway_baileys.accounts(internal_id) ON DELETE CASCADE;
  END IF;
END $$;
`

interface AccountRow {
  id: string
  protocol_definition_id: string
  protocol_version: string
  phone_e164: string
  proxy_url: string
  state: AccountState
  device_jid: string
  auto_connect: boolean
  connection_policy: Account['connectionPolicy']
  idle_disconnect_seconds: number
  post_verify_grace_seconds: number
  sync_policy: Account['syncPolicy']
  session_status: SessionStatus
  session_completeness: SessionCompleteness
  pairing_status: PairingStatus
  pairing_expires_at: Date | null
  metadata_sync_status: Account['metadataSyncStatus']
  has_avatar: boolean | null
  group_count: number | null
  friend_count: number | null
  mutual_contact_count: number | null
  metadata_json: Record<string, unknown>
  state_changed_at: Date
  invalidated_at: Date | null
  reason_category: string
  provider_code: string | null
  created_at: Date
  updated_at: Date
}

interface MessageRow {
  message_id: string
  account_id: string
  recipient_e164: string
  provider_message_id: string
  status: Message['status']
  error_code: string
  queued_at: Date
  sent_at: Date | null
  delivered_at: Date | null
  updated_at: Date
}

function accountFromRow(row: AccountRow): Account {
  return {
    id: row.id,
    protocolDefinitionId: row.protocol_definition_id,
    protocolVersion: row.protocol_version,
    phoneE164: row.phone_e164,
    proxyUrl: row.proxy_url,
    state: row.state,
    deviceJid: row.device_jid,
    autoConnect: row.auto_connect,
    connectionPolicy: row.connection_policy,
    idleDisconnectSeconds: row.idle_disconnect_seconds,
    postVerifyGraceSeconds: row.post_verify_grace_seconds,
    syncPolicy: normalizeSyncPolicy(row.sync_policy),
    sessionStatus: row.session_status,
    sessionCompleteness: row.session_completeness,
    pairingStatus: row.pairing_status,
    pairingExpiresAt: row.pairing_expires_at,
    metadataSyncStatus: row.metadata_sync_status,
    hasAvatar: row.has_avatar,
    groupCount: row.group_count,
    friendCount: row.friend_count,
    mutualContactCount: row.mutual_contact_count,
    metadata: row.metadata_json,
    stateChangedAt: row.state_changed_at,
    invalidatedAt: row.invalidated_at,
    reasonCategory: row.reason_category,
    providerCode: row.provider_code,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  }
}

function messageFromRow(row: MessageRow): Message {
  return {
    messageId: row.message_id,
    accountId: row.account_id,
    recipientE164: row.recipient_e164,
    providerMessageId: row.provider_message_id,
    status: row.status,
    errorCode: row.error_code,
    queuedAt: row.queued_at,
    sentAt: row.sent_at,
    deliveredAt: row.delivered_at,
    updatedAt: row.updated_at,
  }
}

export class PostgresStore implements Store {
  private readonly pool: pg.Pool

  constructor(databaseUrl: string, maxConnections = 50) {
    this.pool = new Pool({ connectionString: databaseUrl, max: maxConnections })
  }

  async migrate(): Promise<void> { await this.pool.query(schema) }
  async ready(): Promise<void> { await this.pool.query('SELECT 1') }
  async close(): Promise<void> { await this.pool.end() }

  async createAccount(input: Pick<Account, 'id' | 'protocolDefinitionId' | 'protocolVersion' | 'phoneE164' | 'proxyUrl' | 'state' | 'connectionPolicy' | 'idleDisconnectSeconds' | 'postVerifyGraceSeconds' | 'syncPolicy'>): Promise<Account> {
    try {
      const result = await this.pool.query<AccountRow>(`
        INSERT INTO wa_gateway_baileys.accounts(internal_id,id,protocol_definition_id,protocol_version,phone_e164,proxy_url,state,connection_policy,idle_disconnect_seconds,post_verify_grace_seconds,sync_policy)
        VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING *`, [nextSnowflakeId(), input.id, input.protocolDefinitionId, input.protocolVersion, input.phoneE164, input.proxyUrl, input.state, input.connectionPolicy, input.idleDisconnectSeconds, input.postVerifyGraceSeconds, input.syncPolicy])
      return accountFromRow(result.rows[0]!)
    } catch (error) {
      if ((error as { code?: string }).code === '23505') throw new GatewayError('conflict', 'account id or phone already exists')
      throw error
    }
  }

  async claimUnpairedAccount(input: Pick<Account, 'id' | 'protocolDefinitionId' | 'protocolVersion' | 'phoneE164' | 'proxyUrl' | 'connectionPolicy' | 'idleDisconnectSeconds' | 'postVerifyGraceSeconds' | 'syncPolicy'>): Promise<Account | null> {
    const result = await this.pool.query<AccountRow>(`
      UPDATE wa_gateway_baileys.accounts AS account
      SET id=$1, proxy_url=$3, protocol_definition_id=$4, protocol_version=$5,
          connection_policy=$6, idle_disconnect_seconds=$7,
          post_verify_grace_seconds=$8, sync_policy=$9, updated_at=NOW(),
          reason_category='orphan_reclaimed', provider_code=NULL
      WHERE account.phone_e164=$2
        AND account.id<>$1
        AND account.state='unpaired'
        AND account.device_jid=''
        AND account.session_status='none'
        AND NOT EXISTS (SELECT 1 FROM wa_gateway_baileys.accounts existing WHERE existing.id=$1)
        AND NOT EXISTS (SELECT 1 FROM wa_gateway_baileys.auth_creds creds WHERE creds.account_id=account.id)
        AND NOT EXISTS (SELECT 1 FROM wa_gateway_baileys.auth_keys keys WHERE keys.account_id=account.id)
        AND NOT EXISTS (SELECT 1 FROM wa_gateway_baileys.messages messages WHERE messages.account_id=account.id)
      RETURNING account.*`, [input.id, input.phoneE164, input.proxyUrl, input.protocolDefinitionId, input.protocolVersion, input.connectionPolicy, input.idleDisconnectSeconds, input.postVerifyGraceSeconds, input.syncPolicy])
    return result.rows[0] ? accountFromRow(result.rows[0]) : null
  }

  async createImportedAccount(
    input: Pick<Account, 'id' | 'protocolDefinitionId' | 'protocolVersion' | 'phoneE164' | 'proxyUrl' | 'state' | 'deviceJid' | 'autoConnect' | 'sessionStatus' | 'sessionCompleteness' | 'connectionPolicy' | 'idleDisconnectSeconds' | 'postVerifyGraceSeconds' | 'syncPolicy'>,
    auth: StoredAuth,
  ): Promise<Account> {
    const client = await this.pool.connect()
    try {
      await client.query('BEGIN')
      const result = await client.query<AccountRow>(`
        INSERT INTO wa_gateway_baileys.accounts
          (internal_id,id,protocol_definition_id,protocol_version,phone_e164,proxy_url,state,device_jid,auto_connect,session_status,session_completeness,connection_policy,idle_disconnect_seconds,post_verify_grace_seconds,sync_policy,reason_category)
        VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,'session_imported') RETURNING *`,
      [nextSnowflakeId(), input.id, input.protocolDefinitionId, input.protocolVersion, input.phoneE164, input.proxyUrl, input.state, input.deviceJid, input.autoConnect, input.sessionStatus, input.sessionCompleteness, input.connectionPolicy, input.idleDisconnectSeconds, input.postVerifyGraceSeconds, input.syncPolicy])
      await client.query(`INSERT INTO wa_gateway_baileys.auth_creds(internal_id,account_internal_id,account_id,value)
        SELECT $1,internal_id,id,$3 FROM wa_gateway_baileys.accounts WHERE id=$2`, [nextSnowflakeId(), input.id, auth.creds])
      for (const key of auth.keys) {
        await client.query(`INSERT INTO wa_gateway_baileys.auth_keys(internal_id,account_internal_id,account_id,category,key_id,value)
          SELECT $1,internal_id,id,$3,$4,$5 FROM wa_gateway_baileys.accounts WHERE id=$2`, [nextSnowflakeId(), input.id, key.type, key.id, key.value])
      }
      await client.query('COMMIT')
      return accountFromRow(result.rows[0]!)
    } catch (error) {
      await client.query('ROLLBACK')
      if ((error as { code?: string }).code === '23505') throw new GatewayError('conflict', 'account id or phone already exists; existing accounts are not overwritten')
      throw error
    } finally { client.release() }
  }

  async listAccounts(): Promise<Account[]> {
    const result = await this.pool.query<AccountRow>('SELECT * FROM wa_gateway_baileys.accounts ORDER BY created_at DESC')
    return result.rows.map(accountFromRow)
  }

  async getAccount(id: string): Promise<Account> {
    const result = await this.pool.query<AccountRow>('SELECT * FROM wa_gateway_baileys.accounts WHERE id=$1', [id])
    if (!result.rows[0]) throw new GatewayError('not_found', 'account does not exist')
    return accountFromRow(result.rows[0])
  }

  async updateAccount(id: string, changes: Partial<Pick<Account, 'phoneE164' | 'proxyUrl' | 'deviceJid' | 'autoConnect' | 'sessionStatus' | 'sessionCompleteness' | 'pairingStatus' | 'pairingExpiresAt' | 'metadataSyncStatus' | 'hasAvatar' | 'groupCount' | 'friendCount' | 'mutualContactCount' | 'connectionPolicy' | 'idleDisconnectSeconds' | 'postVerifyGraceSeconds' | 'syncPolicy' | 'metadata'>>): Promise<Account> {
    const entries = Object.entries(changes)
    if (!entries.length) return this.getAccount(id)
    const columns: Record<string, string> = { phoneE164: 'phone_e164', proxyUrl: 'proxy_url', deviceJid: 'device_jid', autoConnect: 'auto_connect', sessionStatus: 'session_status', sessionCompleteness: 'session_completeness', pairingStatus: 'pairing_status', pairingExpiresAt: 'pairing_expires_at', metadataSyncStatus: 'metadata_sync_status', hasAvatar: 'has_avatar', groupCount: 'group_count', friendCount: 'friend_count', mutualContactCount: 'mutual_contact_count', connectionPolicy: 'connection_policy', idleDisconnectSeconds: 'idle_disconnect_seconds', postVerifyGraceSeconds: 'post_verify_grace_seconds', syncPolicy: 'sync_policy', metadata: 'metadata_json' }
    const values = entries.map(([, value]) => value)
    const setters = entries.map(([key], index) => `${columns[key]}=$${index + 2}`).join(', ')
    try {
      const result = await this.pool.query<AccountRow>(`UPDATE wa_gateway_baileys.accounts SET ${setters}, updated_at=NOW() WHERE id=$1 RETURNING *`, [id, ...values])
      if (!result.rows[0]) throw new GatewayError('not_found', 'account does not exist')
      return accountFromRow(result.rows[0])
    } catch (error) {
      if ((error as { code?: string }).code === '23505') throw new GatewayError('conflict', 'phone already exists')
      throw error
    }
  }

  async transitionAccount(
    id: string,
    state: AccountState,
    changes: Partial<Pick<Account, 'deviceJid' | 'autoConnect' | 'sessionStatus' | 'sessionCompleteness' | 'pairingStatus' | 'pairingExpiresAt' | 'metadataSyncStatus'>>,
    reasonCategory: string,
    providerCode?: string,
  ): Promise<AccountStateTransition> {
    const client = await this.pool.connect()
    try {
      await client.query('BEGIN')
      const currentResult = await client.query<Pick<AccountRow, 'state'>>(
        'SELECT state FROM wa_gateway_baileys.accounts WHERE id=$1 FOR UPDATE', [id])
      const current = currentResult.rows[0]
      if (!current) throw new GatewayError('not_found', 'account does not exist')
      const changed = current.state !== state
      const columns: Record<string, string> = { deviceJid: 'device_jid', autoConnect: 'auto_connect', sessionStatus: 'session_status', sessionCompleteness: 'session_completeness', pairingStatus: 'pairing_status', pairingExpiresAt: 'pairing_expires_at', metadataSyncStatus: 'metadata_sync_status' }
      const entries = Object.entries(changes)
      const values: unknown[] = [id, state, ...entries.map(([, value]) => value)]
      const setters = [
        'state=$2',
        ...entries.map(([key], index) => `${columns[key]}=$${index + 3}`),
      ]
      if (changed) {
        values.push(reasonCategory, providerCode ?? null)
        const reasonIndex = values.length - 1
        const providerIndex = values.length
        setters.push(
          'state_changed_at=NOW()',
          `invalidated_at=CASE WHEN $2='restricted' THEN NOW() ELSE NULL END`,
          `reason_category=$${reasonIndex}`,
          `provider_code=$${providerIndex}`,
        )
      }
      const updated = await client.query<AccountRow>(
        `UPDATE wa_gateway_baileys.accounts SET ${setters.join(', ')},updated_at=NOW() WHERE id=$1 RETURNING *`,
        values,
      )
      await client.query('COMMIT')
      return { account: accountFromRow(updated.rows[0]!), fromState: current.state, changed }
    } catch (error) {
      await client.query('ROLLBACK')
      throw error
    } finally { client.release() }
  }

  async createMessage(message: Message): Promise<{ message: Message; created: boolean }> {
    const result = await this.pool.query<MessageRow>(`
      INSERT INTO wa_gateway_baileys.messages(internal_id,message_id,account_internal_id,account_id,recipient_e164,status,queued_at)
      SELECT $1,$2,internal_id,id,$4,$5,$6 FROM wa_gateway_baileys.accounts WHERE id=$3
      ON CONFLICT(message_id) DO NOTHING RETURNING *`,
    [nextSnowflakeId(), message.messageId, message.accountId, message.recipientE164, message.status, message.queuedAt])
    if (result.rows[0]) return { message: messageFromRow(result.rows[0]), created: true }
    return { message: await this.getMessage(message.messageId), created: false }
  }

  async getMessage(id: string): Promise<Message> {
    const result = await this.pool.query<MessageRow>('SELECT * FROM wa_gateway_baileys.messages WHERE message_id=$1', [id])
    if (!result.rows[0]) throw new GatewayError('not_found', 'message does not exist')
    return messageFromRow(result.rows[0])
  }

  async updateMessage(id: string, changes: Partial<Pick<Message, 'providerMessageId' | 'status' | 'errorCode' | 'sentAt' | 'deliveredAt'>>): Promise<Message> {
    const entries = Object.entries(changes)
    const columns: Record<string, string> = { providerMessageId: 'provider_message_id', status: 'status', errorCode: 'error_code', sentAt: 'sent_at', deliveredAt: 'delivered_at' }
    const values = entries.map(([, value]) => value)
    const setters = entries.map(([key], index) => `${columns[key]}=$${index + 2}`).join(', ')
    const result = await this.pool.query<MessageRow>(`UPDATE wa_gateway_baileys.messages SET ${setters},updated_at=NOW() WHERE message_id=$1 RETURNING *`, [id, ...values])
    if (!result.rows[0]) throw new GatewayError('not_found', 'message does not exist')
    return messageFromRow(result.rows[0])
  }

  async markDeliveredByProvider(accountId: string, providerMessageId: string): Promise<Message | null> {
    const result = await this.pool.query<MessageRow>(`UPDATE wa_gateway_baileys.messages
      SET status='delivered',delivered_at=NOW(),updated_at=NOW()
      WHERE account_id=$1 AND provider_message_id=$2 AND status IN ('queued','sent') RETURNING *`,
    [accountId, providerMessageId])
    return result.rows[0] ? messageFromRow(result.rows[0]) : null
  }

  async getCreds(accountId: string): Promise<unknown | null> {
    const result = await this.pool.query<{ value: unknown }>('SELECT value FROM wa_gateway_baileys.auth_creds WHERE account_id=$1', [accountId])
    return result.rows[0]?.value ?? null
  }

  async setCreds(accountId: string, creds: unknown): Promise<void> {
    await this.pool.query(`INSERT INTO wa_gateway_baileys.auth_creds(internal_id,account_internal_id,account_id,value)
      SELECT $1,internal_id,id,$3 FROM wa_gateway_baileys.accounts WHERE id=$2
      ON CONFLICT(account_id) DO UPDATE SET value=EXCLUDED.value,updated_at=NOW()`, [nextSnowflakeId(), accountId, creds])
  }

  async getKeys(accountId: string, type: string, ids: string[]): Promise<Record<string, unknown>> {
    if (!ids.length) return {}
    const result = await this.pool.query<{ key_id: string; value: unknown }>(
      'SELECT key_id,value FROM wa_gateway_baileys.auth_keys WHERE account_id=$1 AND category=$2 AND key_id=ANY($3)',
      [accountId, type, ids])
    return Object.fromEntries(result.rows.map((row) => [row.key_id, row.value]))
  }

  async setKeys(accountId: string, keys: StoredKey[]): Promise<void> {
    if (!keys.length) return
    const client = await this.pool.connect()
    try {
      await client.query('BEGIN')
      for (const key of keys) {
        if (key.value === null) {
          await client.query('DELETE FROM wa_gateway_baileys.auth_keys WHERE account_id=$1 AND category=$2 AND key_id=$3', [accountId, key.type, key.id])
        } else {
          await client.query(`INSERT INTO wa_gateway_baileys.auth_keys(internal_id,account_internal_id,account_id,category,key_id,value)
            SELECT $1,internal_id,id,$3,$4,$5 FROM wa_gateway_baileys.accounts WHERE id=$2
            ON CONFLICT(account_id,category,key_id) DO UPDATE SET value=EXCLUDED.value,updated_at=NOW()`, [nextSnowflakeId(), accountId, key.type, key.id, key.value])
        }
      }
      await client.query('COMMIT')
    } catch (error) {
      await client.query('ROLLBACK')
      throw error
    } finally { client.release() }
  }

  async getAllKeys(accountId: string): Promise<StoredKey[]> {
    const result = await this.pool.query<{ category: string; key_id: string; value: unknown }>(
      'SELECT category,key_id,value FROM wa_gateway_baileys.auth_keys WHERE account_id=$1 ORDER BY category,key_id', [accountId])
    return result.rows.map((row) => ({ type: row.category, id: row.key_id, value: row.value }))
  }

  async replaceAuth(accountId: string, auth: StoredAuth): Promise<void> {
    const client = await this.pool.connect()
    try {
      await client.query('BEGIN')
      await client.query('DELETE FROM wa_gateway_baileys.auth_keys WHERE account_id=$1', [accountId])
      await client.query(`INSERT INTO wa_gateway_baileys.auth_creds(internal_id,account_internal_id,account_id,value)
        SELECT $1,internal_id,id,$3 FROM wa_gateway_baileys.accounts WHERE id=$2
        ON CONFLICT(account_id) DO UPDATE SET value=EXCLUDED.value,updated_at=NOW()`, [nextSnowflakeId(), accountId, auth.creds])
      for (const key of auth.keys) {
        await client.query(`INSERT INTO wa_gateway_baileys.auth_keys(internal_id,account_internal_id,account_id,category,key_id,value)
          SELECT $1,internal_id,id,$3,$4,$5 FROM wa_gateway_baileys.accounts WHERE id=$2`, [nextSnowflakeId(), accountId, key.type, key.id, key.value])
      }
      await client.query('COMMIT')
    } catch (error) {
      await client.query('ROLLBACK')
      throw error
    } finally { client.release() }
  }

  async clearAuth(accountId: string): Promise<void> {
    const client = await this.pool.connect()
    try {
      await client.query('BEGIN')
      await client.query('DELETE FROM wa_gateway_baileys.auth_keys WHERE account_id=$1', [accountId])
      await client.query('DELETE FROM wa_gateway_baileys.auth_creds WHERE account_id=$1', [accountId])
      await client.query('COMMIT')
    } catch (error) {
      await client.query('ROLLBACK')
      throw error
    } finally { client.release() }
  }
}
