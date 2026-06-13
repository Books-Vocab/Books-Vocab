import { describe, expect, it } from 'vitest'
import { queryKeys } from './queryKeys'

/**
 * Query key 工廠契約 — cache / invalidation 的單一真相。
 *
 * 關鍵不變量：detail / 過濾型 key 必須以其 list key 為前綴，TanStack Query 的
 * partial-match invalidation（invalidateQueries({ queryKey: list }) 命中所有
 * 後代）才能成立。本測試把該前綴關係釘成回歸契約。
 */

describe('queryKeys', () => {
  it('notebook detail key 以 notebooks list key 為前綴（invalidation 可命中）', () => {
    const all = queryKeys.notebooks.all
    const detail = queryKeys.notebooks.detail('nb-1')
    expect(all).toEqual(['notebooks'])
    expect(detail.slice(0, all.length)).toEqual(all)
    expect(detail).toEqual(['notebooks', 'nb-1'])
  })

  it('vocab cards key 含 notebook 過濾維度，缺省為 null（穩定 key）', () => {
    expect(queryKeys.vocab.cards()).toEqual(['vocab', 'cards', null])
    expect(queryKeys.vocab.cards('nb-1')).toEqual(['vocab', 'cards', 'nb-1'])
    // 同 notebook 多次呼叫 key 結構穩定（cache 命中需 referential-stable shape）。
    expect(queryKeys.vocab.cards('nb-1')).toEqual(queryKeys.vocab.cards('nb-1'))
  })

  it('library key 穩定', () => {
    expect(queryKeys.library.all).toEqual(['library'])
  })

  it('每個 domain 皆有 collection root（all），nested key 以其為前綴', () => {
    // 正規化契約：每域有 all collection root，使「invalidate 整個 domain」恆可達；
    // 任何 detail / 過濾型 key 必以 all 為前綴，partial-match invalidation 才成立。
    expect(queryKeys.vocab.all).toEqual(['vocab'])
    expect(queryKeys.vocab.cards().slice(0, 1)).toEqual(queryKeys.vocab.all)
    expect(queryKeys.vocab.cards('nb-1').slice(0, 1)).toEqual(queryKeys.vocab.all)

    expect(queryKeys.podcast.all).toEqual(['podcast'])
    expect(queryKeys.podcast.series.slice(0, 1)).toEqual(queryKeys.podcast.all)

    expect(queryKeys.user.all).toEqual(['user'])
    expect(queryKeys.user.profile.slice(0, 1)).toEqual(queryKeys.user.all)

    expect(queryKeys.notebooks.detail('x').slice(0, 1)).toEqual(queryKeys.notebooks.all)
  })

  it('各 domain 的 root segment 互異（避免跨域誤命中）', () => {
    const roots = [
      queryKeys.notebooks.all[0],
      queryKeys.vocab.all[0],
      queryKeys.library.all[0],
      queryKeys.todayReview.all[0],
      queryKeys.podcast.all[0],
      queryKeys.user.all[0],
    ]
    expect(new Set(roots).size).toBe(roots.length)
  })
})
