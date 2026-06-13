import { useCallback, useEffect, useState } from 'react'
import { useApi } from '../../api/ApiContext'
import { useShellNav } from '../../shell/ShellNavContext'
import type { CardResponse } from '../../api/types'
import type { WordDetailCardFixture } from './fixtures'

/**
 * Word Detail · Card 的 API store — shell=1 時取代 fixture，從 GET /api/vocab/{word}
 * 拉完整卡片並映射成既有 WordDetailCardFixture 形狀（最小 JSX 變動，沿用 buildBlocks）。
 *
 * 誠實邊界：word 來源 = ShellNavContext.params.word 優先、?word= search fallback。
 * parity 路徑（無 shell）不呼叫此 hook，DOM 與 capture 完全不變。
 */

export type WordDetailCardStatus = 'loading' | 'ready' | 'error'

/** 純函式：CardResponse → WordDetailCardFixture。匯出供測試。 */
export function toCardFixture(card: CardResponse): WordDetailCardFixture {
  return {
    compact: false,
    hero: {
      word: card.content,
      partOfSpeech: card.pos ? `${card.pos}.` : null,
      difficultyTier: card.difficultyTier,
    },
    example: card.examples[0] ?? null,
    meaning: card.note
      ? { title: card.meaning, paragraphs: [card.note] }
      : card.meaning
        ? { title: card.meaning, paragraphs: [] }
        : null,
    collocations: card.collocations,
    // CardResponse 無 book/chapter；source 為 enum 字串（reader/manual…）→ 作來源標籤。
    source: { bookTitle: card.source ?? '單字庫', chapterTitle: null },
  }
}

export interface WordDetailCardApiState {
  status: WordDetailCardStatus
  fixture: WordDetailCardFixture | null
  word: string | null
  retry: () => void
}

/** 解析 shell 路徑欲顯示的 word：nav.params.word 優先、?word= search fallback。 */
export function useWordParam(): string | null {
  const nav = useShellNav()
  if (nav.params.word) return nav.params.word
  return new URLSearchParams(window.location.search).get('word')
}

export function useWordDetailCardApiStore(word: string | null): WordDetailCardApiState {
  const api = useApi()
  const [status, setStatus] = useState<WordDetailCardStatus>('loading')
  const [fixture, setFixture] = useState<WordDetailCardFixture | null>(null)

  const load = useCallback(async () => {
    if (!word) {
      setStatus('error')
      return
    }
    setStatus('loading')
    try {
      const card = await api.vocabulary.detail(word)
      setFixture(toCardFixture(card))
      setStatus('ready')
    } catch {
      setStatus('error')
    }
  }, [api, word])

  useEffect(() => {
    load()
  }, [load])

  return { status, fixture, word, retry: load }
}
