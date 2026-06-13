import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { buildMockSession, isDevLoginEnabled } from './devSession'

const STORAGE_KEY = 'kg-web-token'
const USER_KEY = 'kg-web-user-id'

export interface AuthSession {
  userId: string
  token: string
}

export interface AuthContextValue {
  session: AuthSession | null
  isLoading: boolean
  isLoggedIn: boolean
  /** dev/demo 登入是否可用（dev server 或 mock 模式）。false 時不渲染 dev 按鈕。 */
  devLoginEnabled: boolean
  error: string | null
  login: (provider: 'google' | 'apple') => void
  /** 寫入合成 session（免 popup），僅在 devLoginEnabled 時生效。 */
  devLogin: () => void
  logout: () => void
  dismissError: () => void
  getToken: () => string | null
}

const AuthContext = createContext<AuthContextValue | null>(null)

function readStoredSession(): AuthSession | null {
  try {
    const token = localStorage.getItem(STORAGE_KEY)
    const userId = localStorage.getItem(USER_KEY)
    if (token && userId) return { token, userId }
  } catch {
    // localStorage may be disabled in some contexts.
  }
  return null
}

function saveSession(session: AuthSession | null) {
  try {
    if (session) {
      localStorage.setItem(STORAGE_KEY, session.token)
      localStorage.setItem(USER_KEY, session.userId)
    } else {
      localStorage.removeItem(STORAGE_KEY)
      localStorage.removeItem(USER_KEY)
    }
  } catch {
    // ignore
  }
}

function buildAuthUrl(provider: 'google' | 'apple', baseUrl: string): string {
  const path = provider === 'google' ? '/auth/web/google/login' : '/auth/web/apple/login'
  const url = baseUrl ? `${baseUrl.replace(/\/+$/, '')}${path}` : path
  return url
}

/**
 * Web OAuth flow：開 popup 到後端 `/auth/web/{provider}/login`，callback 頁透過
 * postMessage 把 JWT 傳回 opener。token 與 userId 持久化於 localStorage。
 */
export function AuthProvider({
  children,
  baseUrl = '',
}: {
  children: React.ReactNode
  baseUrl?: string
}) {
  const [session, setSession] = useState<AuthSession | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // import.meta.env 在 node 測試環境可能不存在；容錯讀取。
  const env =
    (typeof import.meta !== 'undefined' &&
      (import.meta as { env?: { DEV?: boolean; VITE_API_MODE?: string } }).env) ||
    {}
  const devLoginEnabled = isDevLoginEnabled(env)

  // Hydrate from localStorage on mount.
  useEffect(() => {
    setSession(readStoredSession())
    setIsLoading(false)
  }, [])

  // Listen for postMessage from the OAuth callback popup.
  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      // Only accept messages from our own backend origin or any origin in dev.
      const data = event.data
      if (!data || typeof data !== 'object') return
      if (data.type === 'kg-auth-token' && typeof data.token === 'string' && typeof data.userId === 'string') {
        const next = { token: data.token, userId: data.userId }
        saveSession(next)
        setSession(next)
        setError(null)
      }
      if (data.type === 'kg-auth-error' && typeof data.error === 'string') {
        setError(data.error)
      }
    }
    window.addEventListener('message', handleMessage)
    return () => window.removeEventListener('message', handleMessage)
  }, [])

  const login = useCallback(
    (provider: 'google' | 'apple') => {
      setError(null)
      const width = 500
      const height = 600
      const left = window.screenX + (window.outerWidth - width) / 2
      const top = window.screenY + (window.outerHeight - height) / 2
      const url = buildAuthUrl(provider, baseUrl)
      const features = `width=${width},height=${height},left=${left},top=${top},popup=1`
      const popup = window.open(url, 'kg-oauth', features)
      if (!popup) {
        setError('無法開啟登入視窗，請檢查瀏覽器是否封鎖彈窗。')
      }
    },
    [baseUrl],
  )

  const devLogin = useCallback(() => {
    if (!devLoginEnabled) return
    const next = buildMockSession()
    saveSession(next)
    setSession(next)
    setError(null)
  }, [devLoginEnabled])

  const logout = useCallback(() => {
    saveSession(null)
    setSession(null)
    setError(null)
  }, [])

  const dismissError = useCallback(() => setError(null), [])

  const getToken = useCallback(() => session?.token ?? null, [session])

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      isLoading,
      isLoggedIn: !!session,
      devLoginEnabled,
      error,
      login,
      devLogin,
      logout,
      dismissError,
      getToken,
    }),
    [session, isLoading, devLoginEnabled, error, login, devLogin, logout, dismissError, getToken],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within <AuthProvider>')
  return ctx
}
