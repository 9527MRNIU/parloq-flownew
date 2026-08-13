import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { apiRequest, setBearerToken, type ApiEnvelope } from '../api/client'

export type AuthUser = {
  id?: string | number
  username: string
  groupName?: string | null
  isAdmin?: boolean
}

type AuthValue = {
  user: AuthUser | null
  loading: boolean
  actionPermissions: ReadonlySet<string>
  can: (permissionKey: string) => boolean
  login: (username: string, password: string) => Promise<void>
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

  async function login(username: string, password: string) {
    const response = await apiRequest<ApiEnvelope<{ token?: string; access_token?: string; user?: AuthUser }>>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    setBearerToken(response.data.token || response.data.access_token || null)
    if (response.data.user) setUser(normalizeUser(response.data.user))
    else await loadMe()
  }

  async function logout() {
    try {
      await apiRequest('/api/auth/logout', { method: 'POST' })
    } finally {
      setBearerToken(null)
      setUser(null)
      setActionPermissions(new Set())
    }
  }

  const can = useCallback(
    (permissionKey: string) => Boolean(user?.isAdmin || actionPermissions.has(permissionKey)),
    [actionPermissions, user?.isAdmin],
  )
  const value = useMemo(
    () => ({ user, loading, actionPermissions, can, login, logout }),
    [actionPermissions, can, loading, user],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth 必须在 AuthProvider 中使用')
  return context
}
