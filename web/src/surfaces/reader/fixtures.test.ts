import { describe, expect, it } from 'vitest'
import { READER_FIXTURES, PAPER_SEPIA, PAPER_SEPIA_DEEP } from './fixtures'

// 鏡像 ios/BooksAndVocab/Debug/Scenarios/ReaderChromeScenarios.swift 的 seed：
// 每態的 paper 色、isWebViewReady、loadingPhase、underlineProgress、header 形態、
// totalProgression、showsErrorCard 必須逐欄一致，否則 parity diff 會在 chrome 層
// 失真。書名固定 The Left Hand of Darkness。
describe('READER_FIXTURES', () => {
  it('covers exactly the 6 ReaderChromeScenarios states', () => {
    expect(Object.keys(READER_FIXTURES).sort()).toEqual([
      'error-open-failed',
      'loading-render',
      'loading-vocab',
      'reading-compact',
      'reading-expanded',
      'reading-translation',
    ])
  })

  it('all fixtures use the canonical book title', () => {
    for (const f of Object.values(READER_FIXTURES)) {
      expect(f.bookTitle).toBe('The Left Hand of Darkness')
    }
  })

  it('loading states show the loading card (isWebViewReady=false) with the top underline progress', () => {
    const render = READER_FIXTURES['loading-render']
    expect(render.isWebViewReady).toBe(false)
    expect(render.loadingPhase).toBe('渲染頁面…')
    expect(render.underlineProgress).toBeCloseTo(0.42)
    expect(render.paperColor).toBe(PAPER_SEPIA_DEEP)

    const vocab = READER_FIXTURES['loading-vocab']
    expect(vocab.isWebViewReady).toBe(false)
    expect(vocab.loadingPhase).toBe('標記生字…')
    expect(vocab.underlineProgress).toBeCloseTo(0.68)
    expect(vocab.paperColor).toBe(PAPER_SEPIA)
  })

  it('reading-compact is ready, no overlay, progress badge visible (totalProgression > 0)', () => {
    const f = READER_FIXTURES['reading-compact']
    expect(f.isWebViewReady).toBe(true)
    expect(f.header).toBe('compact')
    expect(f.overlay).toBe('none')
    expect(f.underlineProgress).toBeNull()
    expect(f.totalProgression).toBeCloseTo(0.37)
  })

  it('reading-expanded uses the flat toolbar header', () => {
    const f = READER_FIXTURES['reading-expanded']
    expect(f.header).toBe('expanded')
    expect(f.totalProgression).toBeCloseTo(0.81)
    expect(f.paperColor).toBe(PAPER_SEPIA)
  })

  it('reading-translation keeps compact chrome behind the (R2) translation overlay', () => {
    const f = READER_FIXTURES['reading-translation']
    expect(f.header).toBe('compact')
    expect(f.overlay).toBe('translation')
    expect(f.totalProgression).toBeCloseTo(0.37)
    expect(f.paperColor).toBe(PAPER_SEPIA_DEEP)
  })

  it('error-open-failed shows the error card and hides the progress badge (totalProgression == 0)', () => {
    const f = READER_FIXTURES['error-open-failed']
    expect(f.showsErrorCard).toBe(true)
    expect(f.totalProgression).toBe(0)
    expect(f.header).toBe('compact')
    expect(f.paperColor).toBe(PAPER_SEPIA_DEEP)
  })
})
