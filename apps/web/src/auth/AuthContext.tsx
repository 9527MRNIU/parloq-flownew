import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { apiRequest, type ApiEnvelope } from '../api/client'

export type AuthUser = {
  id?: string | number
  username: string
  groupName?: string | null
  isAdmin?: boolean
  mfaEnabled?: boolean
}

export type LoginResult =
  | { mfaRequired: false }
  | { mfaRequired: true; challengeToken: string; expiresAt?: string }

type AuthValue = {
  user: AuthUser | null
  loading: boolean
  actionPermissions: ReadonlySet<string>
  can: (permissionKey: string) => boolean
  login: (username: string, password: string, turnstileToken?: string) => Promise<LoginResult>
  verifyMfaLogin: (challengeToken: string, code: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthValue | null>(null)

function normalizeUser(value: unknown): AuthUser {
  const root = (value || {}) as Record<string, unknown>
  const row = ((root.user && typeof root.user === 'object') ? root.user : root) as Record<string, unknown>
  const role = String(row.role || '').toLowerCase()
  const explicitAdmin = row.isAdmin ?? row.is_admin
  const isAdmin = explicitAdmin == null ? role === 'admin' : explicitAdmin === true || explicitAdmin === 1 || explicitAdmin === 'true'
  return {
    id: row.id as string | number | undefined,
    username: String(row.username || '用户'),
    groupName: String(row.groupName || row.group_name || (isAdmin ? '管理员' : '普通用户')),
    isAdmin,
    mfaEnabled: Boolean(row.mfaEnabled ?? row.mfa_enabled),
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionPermissions, setActionPermissions] = useState<ReadonlySet<string>>(new Set())

  const loadMe = useCallback(async () => {
    try {
      const response = await apiRequest<ApiEnvelope<AuthUser>>('/api/auth/me')
      setUser(normalizeUser(response.data))
    } catch {
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadMe()
    const unauthorized = () => setUser(null)
    window.addEventListener('parloq:unauthorized', unauthorized)
    return () => window.removeEventListener('parloq:unauthorized', unauthorized)
  }, [loadMe])

  useEffect(() => {
    let cancelled = false
    if (!user || user.isAdmin) {
      setActionPermissions(new Set())
      return () => { cancelled = true }
    }
    setActionPermissions(new Set())
    apiRequest('/api/system/menus/me')
      .then((response) => {
        if (cancelled) return
        const values = (response as { data?: { actionPermissions?: unknown[] } }).data?.actionPermissions
        setActionPermissions(new Set(Array.isArray(values) ? values.map(String) : []))
      })
      .catch(() => {
        if (!cancelled) setActionPermissions(new Set())
      })
    return () => { cancelled = true }
  }, [user])

  async function login(username: string, password: string, turnstileToken?: string) {
    const response = await apiRequest<ApiEnvelope<{
      mfaRequired?: boolean
      challengeToken?: string
      expiresAt?: string
      token?: string
      access_token?: string
      user?: AuthUser
    }>>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password, turnstileToken }),
    })
    if (response.data.mfaRequired) {
      if (!response.data.challengeToken) throw new Error('二步验证请求无效，请重新登录')
      return {
        mfaRequired: true as const,
        challengeToken: response.data.challengeToken,
        expiresAt: response.data.expiresAt,
      }
    }
    if (response.data.user) setUser(normalizeUser(response.data.user))
    else await loadMe()
    return { mfaRequired: false as const }
  }

  async function verifyMfaLogin(challengeToken: string, code: string) {
    const response = await apiRequest<ApiEnvelope<{ user?: AuthUser }>>('/api/auth/mfa/login/verify', {
      method: 'POST',
      body: JSON.stringify({ challengeToken, code }),
    })
    if (response.data.user) setUser(normalizeUser(response.data.user))
    else await loadMe()
  }

  async function logout() {
    try {
      await apiRequest('/api/auth/logout', { method: 'POST' })
    } finally {
      setUser(null)
      setActionPermissions(new Set())
    }
  }

  const can = useCallback(
    (permissionKey: string) => Boolean(user?.isAdmin || actionPermissions.has(permissionKey)),
    [actionPermissions, user?.isAdmin],
  )
  const value = useMemo(
    () => ({ user, loading, actionPermissions, can, login, verifyMfaLogin, logout }),
    [actionPermissions, can, loading, user],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth 必须在 AuthProvider 中使用')
  return context
}
