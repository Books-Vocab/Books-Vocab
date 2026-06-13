import { createContext, useContext, useMemo } from 'react'
import { useAuth } from '../auth'
import { createApiClient, type ApiClient } from './index'

const ApiContext = createContext<ApiClient | null>(null)

/**
 * API client provider — 從 AuthContext 取得動態 token，建立單一 ApiClient 實例。
 * shell 內所有 surface 透過 `useApi()` 讀取同一 client，mock/real 切換由 env 決定。
 */
export function ApiProvider({ children }: { children: React.ReactNode }) {
  const { getToken } = useAuth()
  const api = useMemo(() => createApiClient({ getToken }), [getToken])
  return <ApiContext.Provider value={api}>{children}</ApiContext.Provider>
}

export function useApi(): ApiClient {
  const ctx = useContext(ApiContext)
  if (!ctx) throw new Error('useApi must be used within <ApiProvider>')
  return ctx
}
