import { describe, expect, it } from 'vitest'
import { VOCABULARY_FIXTURES } from './fixtures'
import { filterRows } from './store'

// store 純函式（filterRows）的不變式：query/filter 過濾邏輯。互動 DOM 行為另由
// tools/interaction.mjs（playwright）驗證。
describe('vocabulary store filterRows', () => {
  const rows = VOCABULARY_FIXTURES.populated.rows

  it('empty query + null filter returns all rows (parity 初始態)', () => {
    expect(filterRows(rows, '', null)).toEqual(rows)
  })

  it('query filters by word substring (case-insensitive)', () => {
    const r = filterRows(rows, 'EPHEM', null)
    expect(r.map((x) => x.word)).toEqual(['ephemeral'])
  })

  it('query filters by translation substring', () => {
    const r = filterRows(rows, '雨後', null)
    expect(r.map((x) => x.word)).toEqual(['petrichor'])
  })

  it('non-matching query yields zero rows', () => {
    expect(filterRows(rows, 'zzzzz', null)).toHaveLength(0)
  })

  it('reviewState filter: unlearned keeps all seed rows, due/reviewed empty', () => {
    expect(filterRows(rows, '', 'unlearned')).toHaveLength(rows.length)
    expect(filterRows(rows, '', 'due')).toHaveLength(0)
    expect(filterRows(rows, '', 'reviewed')).toHaveLength(0)
  })

  it('query + filter compose (both must match)', () => {
    expect(filterRows(rows, 'serendipity', 'unlearned')).toHaveLength(1)
    expect(filterRows(rows, 'serendipity', 'due')).toHaveLength(0)
  })
})
