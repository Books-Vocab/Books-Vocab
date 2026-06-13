import { QueryClient } from '@tanstack/react-query'
import { ApiError } from '../api'

/**
 * Query retry predicate — 餵給 TanStack Query 的 `retry` 選項。
 *
 * ApiError 的 http 4xx（client error）重試無意義：請求本身錯（缺權限 / 不存在 /
 * 驗證失敗），重送結果相同 → 立即失敗交 UI 顯示對應狀態。例外 408（request
 * timeout）與 429（rate-limit / quota）雖屬 4xx 但本質暫時（quota 路由如 translate/
 * graph/pipeline 的 429 不該被當永久失敗）→ 視為可重試。network / parse / http 5xx
 * 屬暫時性，退避重試至上限（failureCount 0/1 重試，2 起停 = 共 3 次嘗試）。
 * 非 ApiError 的未知例外亦受同一上限保護，避免無限重試。
 */
const MAX_RETRIES = 2
const TRANSIENT_4XX = new Set([408, 429])

export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (
    error instanceof ApiError &&
    error.kind === 'http' &&
    error.status >= 400 &&
    error.status < 500 &&
    !TRANSIENT_4XX.has(error.status)
  ) {
    return false
  }
  return failureCount < MAX_RETRIES
}

/**
 * 建立 app 共用的 QueryClient。
 *
 * - queries.retry = shouldRetry（4xx 不重試）。
 * - staleTime 30s：同一 query 短時間內重掛載不重抓；mutation 後的 invalidate 仍即時
 *   標記過期 → 立刻重抓，故不影響寫入一致性。
 * - refetchOnWindowFocus 關閉：閱讀 / 學習 app 不需切回視窗就猛刷。
 * - gcTime 5min：離開畫面後 cache 保留 5 分鐘，快速返回不閃 loading。
 * - mutations.retry = false：寫入預設不自動重試（避免重複建立 / 扣額度），由呼叫端決定。
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: shouldRetry,
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
      },
      mutations: {
        retry: false,
      },
    },
  })
}
