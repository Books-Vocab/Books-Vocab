import { describe, expect, it } from 'vitest'
import {
  activeSpanAt,
  buildWordSpans,
  DEMO_DURATION_SEC,
  formatClock,
  nextRate,
  rateLabel,
  sentenceWindows,
} from './timeline'
import { PODCAST_FIXTURES } from './fixtures'

const SENTENCES = (() => {
  const f = PODCAST_FIXTURES['preview-player']
  if (f.kind !== 'preview-player') throw new Error('fixture shape changed')
  return f.sentences
})()

describe('demo timeline', () => {
  it('partitions the 5 sentences across the full 12s clip without gaps', () => {
    const w = sentenceWindows(SENTENCES)
    expect(w).toHaveLength(5)
    expect(w[0].start).toBe(0)
    expect(w[w.length - 1].end).toBe(DEMO_DURATION_SEC)
    // 連續、無縫
    for (let i = 1; i < w.length; i++) expect(w[i].start).toBeCloseTo(w[i - 1].end, 6)
  })

  it('builds one word span per word, monotonically increasing', () => {
    const spans = buildWordSpans(SENTENCES)
    const totalWords = SENTENCES.reduce((n, s) => n + s.text.split(' ').length, 0)
    expect(spans).toHaveLength(totalWords)
    for (let i = 1; i < spans.length; i++) {
      expect(spans[i].start).toBeGreaterThanOrEqual(spans[i - 1].start - 1e-9)
    }
  })

  it('activeSpanAt advances sentence/word as currentTime grows', () => {
    const spans = buildWordSpans(SENTENCES)
    const atStart = activeSpanAt(spans, 0)
    expect(atStart.sentenceIndex).toBe(0)
    expect(atStart.wordIndex).toBe(0)
    // 末段（第 5 句約 9.6–12s）
    const atEnd = activeSpanAt(spans, 11.9)
    expect(atEnd.sentenceIndex).toBe(4)
    // 超出尾端回最後一詞
    const beyond = activeSpanAt(spans, 999)
    expect(beyond.sentenceIndex).toBe(4)
    const lastWords = SENTENCES[4].text.split(' ').length
    expect(beyond.wordIndex).toBe(lastWords - 1)
  })

  it('formatClock renders m:ss locale-free', () => {
    expect(formatClock(0)).toBe('0:00')
    expect(formatClock(6)).toBe('0:06')
    expect(formatClock(72)).toBe('1:12')
    expect(formatClock(-3)).toBe('0:00')
  })

  it('rate cycles ×1 → ×1.5 → ×2 → ×0.75 → ×1', () => {
    expect(nextRate(1)).toBe(1.5)
    expect(nextRate(1.5)).toBe(2)
    expect(nextRate(2)).toBe(0.75)
    expect(nextRate(0.75)).toBe(1)
    expect(rateLabel(1)).toBe('×1')
    expect(rateLabel(1.5)).toBe('×1.5')
    expect(rateLabel(0.75)).toBe('×0.75')
  })
})
