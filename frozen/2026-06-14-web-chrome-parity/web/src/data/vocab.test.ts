import { describe, expect, it } from 'vitest'
import { createApiClient } from '../api'
import { createQueryClient } from './queryClient'
import { queryKeys } from './queryKeys'

/**
 * Vocab 資料層整合 — 不經 React render（無 jsdom），以 QueryClient.fetchQuery 驗證
 * useVocabCardsQuery 背後的 query config（queryKey + queryFn + mock ApiClient）真的
 * 取得卡片，且 notebookId 過濾維度產生獨立 cache。hook 本身的 render 行為由 headless
 * tools/interaction.mjs 在真實瀏覽器中覆蓋（Vocabulary 搜尋/過濾/展開）。
 */

describe('vocab 資料層整合（mock backend）', () => {
  it('fetchQuery(vocab.cards) 經 mock ApiClient 取得卡片列表', async () => {
    const api = createApiClient({ mode: 'mock', getToken: () => 'demo-access-token' })
    const qc = createQueryClient()
    const data = await qc.fetchQuery({
      queryKey: queryKeys.vocab.cards(),
      queryFn: () => api.vocabulary.list({}),
    })
    expect(Array.isArray(data)).toBe(true)
    expect(data.length).toBeGreaterThan(0)
    expect(data[0]).toHaveProperty('content')
  })

  it('不同 notebookId → 獨立 cache key，互不命中', async () => {
    const qc = createQueryClient()
    let allCalls = 0
    let scopedCalls = 0
    await qc.fetchQuery({
      queryKey: queryKeys.vocab.cards(),
      queryFn: async () => {
        allCalls += 1
        return []
      },
    })
    await qc.fetchQuery({
      queryKey: queryKeys.vocab.cards('nb-1'),
      queryFn: async () => {
        scopedCalls += 1
        return []
      },
    })
    // 不同 notebookId → 不同 key → 各自 fetch；若誤判同 key 則 scopedCalls 會是 0。
    expect([allCalls, scopedCalls]).toEqual([1, 1])
  })
})
