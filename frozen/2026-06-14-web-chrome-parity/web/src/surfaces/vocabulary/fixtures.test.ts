import { describe, expect, it } from 'vitest'
import { VOCABULARY_FIXTURES } from './fixtures'

// 鏡像 ios/BooksAndVocab/Debug/Scenarios/VocabularyListViewScenarios.swift 的 seed：
// 單字、詞性、翻譯、三態 segment 計數、CTA 數字必須逐字一致，否則 parity diff 會
// 在文字層失真。關鍵不變式：seed 全是 synced unlearned 卡 → due/reviewed 恆 0、
// unlearned = row 數、CTA = unlearned；pendingAdd 不進 knowledge list（populated
// 第五筆 quintessential 不出現）→ row 數 4 而非 5。
describe('VOCABULARY_FIXTURES', () => {
  it('populated mirrors the synced subset (4 unlearned rows, pendingAdd excluded)', () => {
    const f = VOCABULARY_FIXTURES.populated
    expect(f.stats).toEqual({ unlearned: 4, due: 0, reviewed: 0 })
    expect(f.ctaCount).toBe(4)
    expect(f.rows.map((r) => [r.word, r.partOfSpeech, r.translation])).toEqual([
      ['serendipity', 'n.', '機緣巧合'],
      ['ephemeral', 'adj.', '短暫的'],
      ['petrichor', 'n.', '雨後泥土香'],
      ['ineffable', 'adj.', '難以言喻的'],
    ])
  })

  it('single scenario has one unlearned row, CTA 1', () => {
    const f = VOCABULARY_FIXTURES.single
    expect(f.stats).toEqual({ unlearned: 1, due: 0, reviewed: 0 })
    expect(f.ctaCount).toBe(1)
    expect(f.rows).toHaveLength(1)
    expect(f.rows[0].word).toBe('serendipity')
  })

  it('empty scenario shows the zero-data CTA card, no rows, no CTA pill', () => {
    const f = VOCABULARY_FIXTURES.empty
    expect(f.rows).toHaveLength(0)
    expect(f.stats).toEqual({ unlearned: 0, due: 0, reviewed: 0 })
    expect(f.ctaCount).toBe(0)
    expect(f.empty?.icon).toBe('books')
    expect(f.empty?.actionTitle).toBe('重新整理')
    expect(f.empty?.title).toBe('尚無已收錄單字')
  })

  it('unlearned seed renders the first-round detail label on every row', () => {
    for (const scenario of ['populated', 'single'] as const) {
      for (const row of VOCABULARY_FIXTURES[scenario].rows) {
        expect(row.detail).toBe('首輪 12h')
      }
    }
  })

  it('stat counts stay consistent: unlearned == rows, due/reviewed == 0, cta == unlearned', () => {
    for (const scenario of ['populated', 'single'] as const) {
      const f = VOCABULARY_FIXTURES[scenario]
      expect(f.stats.unlearned).toBe(f.rows.length)
      expect(f.stats.due).toBe(0)
      expect(f.stats.reviewed).toBe(0)
      expect(f.ctaCount).toBe(f.stats.unlearned)
    }
  })
})
