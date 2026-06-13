import { describe, expect, it } from 'vitest'
import { createApiClient } from '../api'
import { createQueryClient } from './queryClient'
import { queryKeys } from './queryKeys'

/**
 * P2 資料層端到端整合 — 不經 React render（無 jsdom），直接以 QueryClient.fetchQuery
 * 驗證「query key + queryFn + ApiClient(mock)」串起來真的取得資料，以及 createQueryClient
 * 的 cache 語意（staleTime dedup / invalidate 觸發 refetch）符合契約。
 */

describe('P2 資料層整合（mock backend）', () => {
  it('fetchQuery(notebooks) 經 mock ApiClient 取得真實列表', async () => {
    // mock backend 對受保護路由要求 Bearer token（無 token → 401）。
    const api = createApiClient({ mode: 'mock', getToken: () => 'demo-access-token' })
    const qc = createQueryClient()
    const data = await qc.fetchQuery({
      queryKey: queryKeys.notebooks.all,
      queryFn: () => api.notebook.list(),
    })
    expect(Array.isArray(data)).toBe(true)
    expect(data.length).toBeGreaterThan(0)
    expect(data[0]).toHaveProperty('id')
  })

  it('staleTime 內重 fetch 命中 cache（不重呼叫 queryFn）；invalidate 後重抓', async () => {
    const qc = createQueryClient()
    let calls = 0
    const queryFn = async () => {
      calls += 1
      return [{ id: `nb-${calls}` }]
    }
    const key = queryKeys.notebooks.all

    await qc.fetchQuery({ queryKey: key, queryFn })
    expect(calls).toBe(1)

    // staleTime 30s 內 → 命中 cache，不重呼叫。
    await qc.fetchQuery({ queryKey: key, queryFn })
    expect(calls).toBe(1)

    // invalidate（mutation onSuccess 模擬）→ 標記過期 → 下次 fetch 重抓。
    await qc.invalidateQueries({ queryKey: key })
    await qc.fetchQuery({ queryKey: key, queryFn })
    expect(calls).toBe(2)
  })

  it('invalidate list key 以 partial-match 失效 detail（前綴階層）', async () => {
    const qc = createQueryClient()
    let listCalls = 0
    let detailCalls = 0
    await qc.fetchQuery({
      queryKey: queryKeys.notebooks.all,
      queryFn: async () => {
        listCalls += 1
        return []
      },
    })
    await qc.fetchQuery({
      queryKey: queryKeys.notebooks.detail('nb-1'),
      queryFn: async () => {
        detailCalls += 1
        return { id: 'nb-1' }
      },
    })
    expect([listCalls, detailCalls]).toEqual([1, 1])

    // 失效 list key → detail（['notebooks','nb-1']）因前綴匹配一併過期。
    await qc.invalidateQueries({ queryKey: queryKeys.notebooks.all })
    await qc.fetchQuery({
      queryKey: queryKeys.notebooks.detail('nb-1'),
      queryFn: async () => {
        detailCalls += 1
        return { id: 'nb-1' }
      },
    })
    expect(detailCalls).toBe(2)
  })
})
