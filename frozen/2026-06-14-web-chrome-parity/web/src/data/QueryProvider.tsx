import { QueryClientProvider } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { createQueryClient } from './queryClient'

/**
 * TanStack Query provider — 掛在 <ApiProvider> 之內、shell 之外，令所有 surface 的
 * query/mutation hooks 共用單一 QueryClient（cache / dedup / invalidation）。
 *
 * client 以 useState lazy-init 持有：每個 App 實例一個、跨 re-render 穩定，且不在
 * 模組層建立（避免測試/SSR 共用單例污染）。parity capture 路徑不掛此 provider。
 */
export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(createQueryClient)
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}
