import { describe, expect, it } from 'vitest'
import {
  READER_FIXTURES,
  TRANSLATION_FIXTURES,
  PAPER_SEPIA,
  PAPER_SEPIA_DEEP,
  translationFixtureFor,
} from './fixtures'

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
      expect(f!.bookTitle).toBe('The Left Hand of Darkness')
    }
  })

  it('loading states show the loading card (isWebViewReady=false) with the top underline progress', () => {
    const render = READER_FIXTURES['loading-render']!
    expect(render.isWebViewReady).toBe(false)
    expect(render.loadingPhase).toBe('渲染頁面…')
    expect(render.underlineProgress).toBeCloseTo(0.42)
    expect(render.paperColor).toBe(PAPER_SEPIA_DEEP)

    const vocab = READER_FIXTURES['loading-vocab']!
    expect(vocab.isWebViewReady).toBe(false)
    expect(vocab.loadingPhase).toBe('標記生字…')
    expect(vocab.underlineProgress).toBeCloseTo(0.68)
    expect(vocab.paperColor).toBe(PAPER_SEPIA)
  })

  it('reading-compact is ready, no overlay, progress badge visible (totalProgression > 0)', () => {
    const f = READER_FIXTURES['reading-compact']!
    expect(f.isWebViewReady).toBe(true)
    expect(f.header).toBe('compact')
    expect(f.overlay).toBe('none')
    expect(f.underlineProgress).toBeNull()
    expect(f.totalProgression).toBeCloseTo(0.37)
  })

  it('reading-expanded uses the flat toolbar header', () => {
    const f = READER_FIXTURES['reading-expanded']!
    expect(f.header).toBe('expanded')
    expect(f.totalProgression).toBeCloseTo(0.81)
    expect(f.paperColor).toBe(PAPER_SEPIA)
  })

  it('reading-translation keeps compact chrome behind the (R2) translation overlay', () => {
    const f = READER_FIXTURES['reading-translation']!
    expect(f.header).toBe('compact')
    expect(f.overlay).toBe('translation')
    expect(f.totalProgression).toBeCloseTo(0.37)
    expect(f.paperColor).toBe(PAPER_SEPIA_DEEP)
  })

  it('error-open-failed shows the error card and hides the progress badge (totalProgression == 0)', () => {
    const f = READER_FIXTURES['error-open-failed']!
    expect(f.showsErrorCard).toBe(true)
    expect(f.totalProgression).toBe(0)
    expect(f.header).toBe('compact')
    expect(f.paperColor).toBe(PAPER_SEPIA_DEEP)
  })

  it('only reading-translation carries a panel; chrome states are panel-less', () => {
    for (const [id, f] of Object.entries(READER_FIXTURES)) {
      if (id === 'reading-translation') {
        expect(f.panel).not.toBeNull()
        expect(f.overlay).toBe('translation')
      } else {
        expect(f.panel).toBeNull()
        expect(f.overlay).toBe('none')
      }
    }
  })

  it('reading-translation panel mirrors the Reading · Translation Overlay ref (resilient, expanded)', () => {
    const p = READER_FIXTURES['reading-translation']!.panel!
    expect(p.word).toBe('resilient')
    expect(p.partOfSpeech).toBe('adj.')
    expect(p.translation).toBe('有韌性的；能快速恢復的')
    expect(p.isExpanded).toBe(true)
    expect(p.explanation).toBe('在這段語境中指角色面對壓力後仍迅速回到穩定狀態。')
  })
})

// 鏡像 ios/BooksAndVocab/Debug/Scenarios/ReaderScenarios.swift「Reader · Translation」
// 6 態（TranslationPanelPreviewScene，word gorgeous）。每態的 contentMode 軸
// （translation / loading / error / explanationOnly）必須與 catalog seed 對齊。
describe('TRANSLATION_FIXTURES', () => {
  it('covers exactly the 6 Reader · Translation states', () => {
    expect(Object.keys(TRANSLATION_FIXTURES).sort()).toEqual([
      'translation-collapsed',
      'translation-error',
      'translation-expanded',
      'translation-explain-only',
      'translation-explanation-error',
      'translation-loading',
    ])
  })

  it('all fixtures use the canonical word gorgeous / adj.', () => {
    for (const f of Object.values(TRANSLATION_FIXTURES)) {
      expect(f.word).toBe('gorgeous')
      expect(f.partOfSpeech).toBe('adj.')
    }
  })

  it('expanded shows translation + explanation; collapsed hides the explanation', () => {
    const exp = TRANSLATION_FIXTURES['translation-expanded']
    expect(exp.isExpanded).toBe(true)
    expect(exp.translation).not.toBeNull()
    expect(exp.explanation).not.toBeNull()

    const col = TRANSLATION_FIXTURES['translation-collapsed']
    expect(col.isExpanded).toBe(false)
    expect(col.translation).not.toBeNull()
    expect(col.explanation).toBeNull()
  })

  it('loading drops the translation and uses the status message', () => {
    const f = TRANSLATION_FIXTURES['translation-loading']
    expect(f.isLoading).toBe(true)
    expect(f.translation).toBeNull()
    expect(f.statusMessage).toBe('Added to Vocabulary')
  })

  it('translation-error carries the timeout message and no translation', () => {
    const f = TRANSLATION_FIXTURES['translation-error']
    expect(f.translation).toBeNull()
    expect(f.translationError).toBe('翻譯服務逾時，請稍後再試。')
  })

  it('explain-only is the sentence mode (no translation hero)', () => {
    const f = TRANSLATION_FIXTURES['translation-explain-only']
    expect(f.isExplanationOnly).toBe(true)
    expect(f.explanation).not.toBeNull()
    // ref scenario 用預設 isPanelLarge=false（小卡）。
    expect(f.isPanelLarge).toBe(false)
  })

  it('explanation-error keeps the translation but errors the explanation section', () => {
    const f = TRANSLATION_FIXTURES['translation-explanation-error']
    expect(f.isExpanded).toBe(true)
    expect(f.explanation).toBeNull()
    expect(f.explanationError).toBe('語境分析暫時不可用。')
  })

  it('translationFixtureFor resolves translation-* ids and rejects chrome ids', () => {
    expect(translationFixtureFor('translation-expanded')).not.toBeNull()
    expect(translationFixtureFor('reading-compact')).toBeNull()
    expect(translationFixtureFor('error-open-failed')).toBeNull()
  })
})
