import { describe, expect, it } from 'vitest'
import { formatShareText, speakWord } from './share'
import type { VocabRowFixture } from './fixtures'

const ROW: VocabRowFixture = {
  word: 'serendipity',
  partOfSpeech: 'n.',
  translation: '機緣巧合',
  detail: '首輪 12h',
  reviewState: 'unlearned',
  expansion: {
    explanation: '意外發現美好事物的能力或運氣。',
    example: 'Finding that café was pure serendipity.',
  },
}

describe('formatShareText', () => {
  it('formats "word — meaning (example)" when an example exists', () => {
    expect(formatShareText(ROW)).toBe(
      'serendipity — 機緣巧合 (Finding that café was pure serendipity.)',
    )
  })

  it('omits the parenthetical when the example is empty', () => {
    const noExample: VocabRowFixture = {
      ...ROW,
      expansion: { explanation: ROW.expansion.explanation, example: '' },
    }
    expect(formatShareText(noExample)).toBe('serendipity — 機緣巧合')
  })

  it('trims surrounding whitespace on each field', () => {
    const padded: VocabRowFixture = {
      ...ROW,
      word: '  serendipity  ',
      translation: '  機緣巧合 ',
      expansion: { explanation: ROW.expansion.explanation, example: '  an example.  ' },
    }
    expect(formatShareText(padded)).toBe('serendipity — 機緣巧合 (an example.)')
  })
})

describe('speakWord', () => {
  it('is a graceful no-op (returns false) when speechSynthesis is unsupported', () => {
    // node test environment has no window/speechSynthesis → must not throw.
    expect(speakWord('serendipity')).toBe(false)
  })

  it('speaks and returns true when a speechSynthesis shim is present', () => {
    const utterances: unknown[] = []
    const fakeSynth = {
      cancel: () => {},
      speak: (u: unknown) => utterances.push(u),
    }
    const fakeCtor = class {
      text: string
      lang = ''
      constructor(text: string) {
        this.text = text
      }
    }
    const g = globalThis as unknown as {
      speechSynthesis?: unknown
      SpeechSynthesisUtterance?: unknown
    }
    const prevSynth = g.speechSynthesis
    const prevCtor = g.SpeechSynthesisUtterance
    g.speechSynthesis = fakeSynth
    g.SpeechSynthesisUtterance = fakeCtor
    try {
      expect(speakWord('serendipity')).toBe(true)
      expect(utterances).toHaveLength(1)
      expect((utterances[0] as { text: string }).text).toBe('serendipity')
      expect((utterances[0] as { lang: string }).lang).toBe('en-US')
    } finally {
      g.speechSynthesis = prevSynth
      g.SpeechSynthesisUtterance = prevCtor
    }
  })
})
