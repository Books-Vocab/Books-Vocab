import { useQuery } from '@tanstack/react-query'
import { ApiError } from '../api'
import { useApi } from '../api/ApiContext'
import type { CardResponse } from '../api/types'
import { queryKeys } from './queryKeys'

/**
 * Vocabulary domain 的 TanStack Query hook — P2.2 首個 surface 遷移的資料引擎。
 *
 * 取代 useVocabApiStore 原本手刻的 fetch（useState(status) + useEffect + 自管
 * retry）：useQuery 提供跨 surface cache / dedup（同 notebookId 多處掛載只打一次）、
 * 正確 retry 策略（5xx/network 退避、4xx 立即失敗、408/429 視為暫時）、staleTime
 * 去抖；寫入面（新增/刪除卡片）只需 invalidate queryKeys.vocab.all 即一致刷新。
 *
 * notebookId 為過濾維度（null = 全部卡片），併入 queryKey → 不同 notebook 各自快取。
 * error generic = ApiError，呼叫端可直接讀 .status/.code 分流（無需 instanceof 收窄）。
 */
export function useVocabCardsQuery(notebookId: string | null) {
  const api = useApi()
  // 正規化 falsy（null / 空字串如 ?notebook_id=）為 null，使 queryKey 與 queryFn 對齊：
  // 兩者皆「無過濾 = 全部卡片」走同一 cache 槽，避免空字串另開冗餘 key。
  const id = notebookId || null
  return useQuery<CardResponse[], ApiError>({
    queryKey: queryKeys.vocab.cards(id ?? undefined),
    queryFn: () => api.vocabulary.list(id ? { notebookId: id } : {}),
  })
}
