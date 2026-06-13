import { describe, expect, it } from 'vitest'
import { PODCAST_FIXTURES } from './fixtures'

// 鏡像 ios/BooksAndVocab/Debug/Scenarios/PodcastPlayerViewScenarios.swift 的 seed：
// 字幕句子（sampleSRT 折疊成句）、active 句、時鐘與進度（durationSec 1832、
// currentSec 6.09）必須與 catalog 一致，否則 parity diff 在文字/版面層失真。
describe('PODCAST_FIXTURES', () => {
  it('preview-player mirrors the catalog seam (1832s duration, 6.09s playhead)', () => {
    const f = PODCAST_FIXTURES['preview-player']
    expect(f.kind).toBe('preview-player')
    if (f.kind !== 'preview-player') return
    expect(f.elapsed).toBe('00:06')
    expect(f.total).toBe('30:32') // 1832s → %02d:%02d
    // progress = currentSec / durationSec
    expect(f.progress).toBeCloseTo(6.09 / 1832, 6)
    expect(f.rate).toBe('×1')
  })

  it('preview-player lights exactly one active sentence (3rd, word "quietly")', () => {
    const f = PODCAST_FIXTURES['preview-player']
    if (f.kind !== 'preview-player') return
    const active = f.sentences.filter((s) => s.isActive)
    expect(active).toHaveLength(1)
    expect(active[0].text).toBe('Easy distraction quietly erodes our focus.')
    // activeWordIndex 指向 "quietly"（0-based 第 3 個詞）
    expect(active[0].text.split(' ')[active[0].activeWordIndex]).toBe('quietly')
    // 非 active 句不帶 underline
    for (const s of f.sentences) {
      if (!s.isActive) expect(s.activeWordIndex).toBe(-1)
    }
  })

  it('preview-player transcript is the first-viewport slice (5 sentences, scroll offset 0)', () => {
    const f = PODCAST_FIXTURES['preview-player']
    if (f.kind !== 'preview-player') return
    expect(f.sentences.map((s) => s.text)).toEqual([
      'Welcome back to Deep Work, Decoded.',
      'Today we trace the comfort crisis.',
      'Easy distraction quietly erodes our focus.',
      'The thesis is simple and a little uncomfortable.',
      'Discomfort chosen on purpose builds durable attention.',
    ])
  })

  it('locked-gate is the guest sign-in state', () => {
    expect(PODCAST_FIXTURES['locked-gate'].kind).toBe('locked-gate')
  })
})
