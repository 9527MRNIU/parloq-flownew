import pg from 'pg'
import type { Account, AccountState, AccountStateTransition, Message, SessionCompleteness, SessionStatus, StoredAuth, StoredKey } from './domain.js'
import { GatewayError } from './domain.js'

const { Pool } = pg

export interface Store {
  migrate(): Promise<void>
  ready(): Promise<void>
  close(): Promise<void>
  createAccount(account: Pick<Account, 'id' | 'phoneE164' | 'proxyUrl' | 'state'>): Promise<Account>
  createImportedAccount(account: Pick<Account, 'id' | 'phoneE164' | 'proxyUrl' | 'state' | 'deviceJid' | 'autoConnect' | 'sessionStatus' | 'sessionCompleteness'>, auth: StoredAuth): Promise<Account>
  listAccounts(): Promise<Account[]>
  getAccount(id: string): Promise<Account>
  updateAccount(id: string, changes: Partial<Pick<Account, 'phoneE164' | 'proxyUrl' | 'deviceJid' | 'autoConnect' | 'sessionStatus' | 'sessionCompleteness' | 'metadataSyncStatus' | 'hasAvatar' | 'groupCount' | 'friendCount' | 'mutualContactCount'>>): Promise<Account>
  transitionAccount(id: string, state: AccountState, changes: Partial<Pick<Account, 'deviceJid' | 'autoConnect' | 'sessionStatus' | 'sessionCompleteness' | 'metadataSyncStatus'>>, reasonCategory: string, providerCode?: string): Promise<AccountStateTransition>
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
  phone_e164 TEXT NOT NULL UNIQUE,
  proxy_url TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL DEFAULT 'unpaired',
  device_jid TEXT NOT NULL DEFAULT '',
  auto_connect BOOLEAN NOT NULL DEFAULT FALSE,
  session_status TEXT NOT NULL DEFAULT 'none',
  session_completeness TEXT NOT NULL DEFAULT 'none',
  metadata_sync_status TEXT NOT NULL DEFAULT 'pending',
  has_avatar BOOLEAN,
  group_count INTEGER,
  friend_count INTEGER,
  mutual_contact_count INTEGER,
  state_changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  invalidated_at TIMESTAMPTZ,
  reason_category TEXT NOT NULL DEFAULT 'created',
  provider_code TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE wa_gateway_baileys.accounts
  ADD COLUMN IF NOT EXISTS metadata_sync_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE wa_gateway_baileys.accounts ADD COLUMN IF NOT EXISTS has_avatar BOOLEAN;
ALTER TABLE wa_gateway_baileys.accounts ADD COLUMN IF NOT EXISTS group_count INTEGER;
ALTER TABLE wa_gateway_baileys.accounts ADD COLUMN IF NOT EXISTS friend_count INTEGER;
ALTER TABLE wa_gateway_baileys.accounts ADD COLUMN IF NOT EXISTS mutual_contact_count INTEGER;
ALTER TABLE wa_gateway_baileys.accounts ADD COLUMN IF NOT EXISTS state_changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE wa_gateway_baileys.accounts ADD COLUMN IF NOT EXISTS invalidated_at TIMESTAMPTZ;
ALTER TABLE wa_gateway_baileys.accounts ADD COLUMN IF NOT EXISTS reason_category TEXT NOT NULL DEFAULT 'created';
ALTER TABLE wa_gateway_baileys.accounts ADD COLUMN IF NOT EXISTS provider_code TEXT;
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
`

interface AccountRow {
  id: string
  phone_e164: string
  proxy_url: string
  state: AccountState
  device_jid: string
  auto_connect: boolean
  session_status: SessionStatus
  session_completeness: SessionCompleteness
  metadata_sync_status: Account['metadataSyncStatus']
  has_avatar: boolean | null
  group_count: number | null
  friend_count: number | null
  mutual_contact_count: number | null
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
    phoneE164: row.phone_e164,
    proxyUrl: row.proxy_url,
    state: row.state,
    deviceJid: row.device_jid,
    autoConnect: row.auto_connect,
    sessionStatus: row.session_status,
    sessionCompleteness: row.session_completeness,
    metadataSyncStatus: row.metadata_sync_status,
    hasAvatar: row.has_avatar,
    groupCount: row.group_count,
    friendCount: row.friend_count,
    mutualContactCount: row.mutual_contact_count,
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

  async createAccount(input: Pick<Account, 'id' | 'phoneE164' | 'proxyUrl' | 'state'>): Promise<Account> {
    try {
      const result = await this.pool.query<AccountRow>(`
        INSERT INTO wa_gateway_baileys.accounts(id, phone_e164, proxy_url, state)
        VALUES($1,$2,$3,$4) RETURNING *`, [input.id, input.phoneE164, input.proxyUrl, input.state])
      return accountFromRow(result.rows[0]!)
    } catch (error) {
      if ((error as { code?: string }).code === '23505') throw new GatewayError('conflict', 'account id or phone already exists')
      throw error
    }
  }

  async createImportedAccount(
    input: Pick<Account, 'id' | 'phoneE164' | 'proxyUrl' | 'state' | 'deviceJid' | 'autoConnect' | 'sessionStatus' | 'sessionCompleteness'>,
    auth: StoredAuth,
  ): Promise<Account> {
    const client = await this.pool.connect()
    try {
      await client.query('BEGIN')
      const result = await client.query<AccountRow>(`
        INSERT INTO wa_gateway_baileys.accounts
          (id,phone_e164,proxy_url,state,device_jid,auto_connect,session_status,session_completeness,reason_category)
        VALUES($1,$2,$3,$4,$5,$6,$7,$8,'session_imported') RETURNING *`,
      [input.id, input.phoneE164, input.proxyUrl, input.state, input.deviceJid, input.autoConnect, input.sessionStatus, input.sessionCompleteness])
      await client.query('INSERT INTO wa_gateway_baileys.auth_creds(account_id,value) VALUES($1,$2)', [input.id, auth.creds])
      for (const key of auth.keys) {
        await client.query('INSERT INTO wa_gateway_baileys.auth_keys(account_id,category,key_id,value) VALUES($1,$2,$3,$4)', [input.id, key.type, key.id, key.value])
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

  async updateAccount(id: string, changes: Partial<Pick<Account, 'phoneE164' | 'proxyUrl' | 'deviceJid' | 'autoConnect' | 'sessionStatus' | 'sessionCompleteness' | 'metadataSyncStatus' | 'hasAvatar' | 'groupCount' | 'friendCount' | 'mutualContactCount'>>): Promise<Account> {
    const entries = Object.entries(changes)
    if (!entries.length) return this.getAccount(id)
    const columns: Record<string, string> = { phoneE164: 'phone_e164', proxyUrl: 'proxy_url', deviceJid: 'device_jid', autoConnect: 'auto_connect', sessionStatus: 'session_status', sessionCompleteness: 'session_completeness', metadataSyncStatus: 'metadata_sync_status', hasAvatar: 'has_avatar', groupCount: 'group_count', friendCount: 'friend_count', mutualContactCount: 'mutual_contact_count' }
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
    changes: Partial<Pick<Account, 'deviceJid' | 'autoConnect' | 'sessionStatus' | 'sessionCompleteness' | 'metadataSyncStatus'>>,
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
      const columns: Record<string, string> = { deviceJid: 'device_jid', autoConnect: 'auto_connect', sessionStatus: 'session_status', sessionCompleteness: 'session_completeness', metadataSyncStatus: 'metadata_sync_status' }
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
      INSERT INTO wa_gateway_baileys.messages(message_id,account_id,recipient_e164,status,queued_at)
      VALUES($1,$2,$3,$4,$5) ON CONFLICT(message_id) DO NOTHING RETURNING *`,
    [message.messageId, message.accountId, message.recipientE164, message.status, message.queuedAt])
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
    await this.pool.query(`INSERT INTO wa_gateway_baileys.auth_creds(account_id,value) VALUES($1,$2)
      ON CONFLICT(account_id) DO UPDATE SET value=EXCLUDED.value,updated_at=NOW()`, [accountId, creds])
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
          await client.query(`INSERT INTO wa_gateway_baileys.auth_keys(account_id,category,key_id,value) VALUES($1,$2,$3,$4)
            ON CONFLICT(account_id,category,key_id) DO UPDATE SET value=EXCLUDED.value,updated_at=NOW()`, [accountId, key.type, key.id, key.value])
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
      await client.query(`INSERT INTO wa_gateway_baileys.auth_creds(account_id,value) VALUES($1,$2)
        ON CONFLICT(account_id) DO UPDATE SET value=EXCLUDED.value,updated_at=NOW()`, [accountId, auth.creds])
      for (const key of auth.keys) {
        await client.query('INSERT INTO wa_gateway_baileys.auth_keys(account_id,category,key_id,value) VALUES($1,$2,$3,$4)', [accountId, key.type, key.id, key.value])
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
