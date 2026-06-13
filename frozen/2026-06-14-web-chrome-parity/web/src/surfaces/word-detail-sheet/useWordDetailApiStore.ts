import { useCallback, useEffect, useState } from 'react'
import { useApi } from '../../api/ApiContext'
import { useShellNav } from '../../shell/ShellNavContext'
import type { CardLinkSummaryResponse, CardResponse } from '../../api/types'

/**
 * Word Detail（sheet / card 共用）的 API store — shell=1 時取代 fixture 載入態。
 * 從 GET /api/vocab/{word} 拉完整卡片，映射成 web 呈現模型（含 collocations /
 * inflections / linksByKind / difficultyTier）。非 ready 態由畫面自行渲染。
 *
 * 誠實邊界：word 來源 = ShellNavContext.params.word（nav 提供）優先，
 * window.location.search 的 ?word= 為 deep-link fallback。parity 路徑（無 shell）
 * 不呼叫此 hook，DOM 與 capture 完全不變。
 */

export type WordDetailStatus = 'loading' | 'ready' | 'error'

/** 一個連結群組（依 kind 分組）的 web 呈現模型。 */
export interface WordDetailLinkGroup {
  kind: string
  links: CardLinkSummaryResponse[]
}

/** Word Detail 的完整 web 呈現模型（鏡射 iOS WordDetailPresentation）。 */
export interface WordDetailPresentation {
  word: string
  pos: string | null
  meaning: string
  note: string | null
  difficultyTier: string | null
  collocations: string[]
  examples: string[]
  inflections: string[]
  /** linksByKind 攤平成穩定排序（kind 字母序）的群組陣列，供列表渲染。 */
  linkGroups: WordDetailLinkGroup[]
}

/** 純函式：CardResponse → WordDetailPresentation。匯出供測試。 */
export function toWordDetail(card: CardResponse): WordDetailPresentation {
  const linkGroups: WordDetailLinkGroup[] = Object.entries(card.linksByKind)
    .map(([kind, links]) => ({ kind, links: links.filter((l) => !l.hidden) }))
    .filter((g) => g.links.length > 0)
    .sort((a, b) => (a.kind < b.kind ? -1 : a.kind > b.kind ? 1 : 0))

  return {
    word: card.content,
    pos: card.pos,
    meaning: card.meaning,
    note: card.note,
    difficultyTier: card.difficultyTier,
    collocations: card.collocations,
    examples: card.examples,
    inflections: card.inflections,
    linkGroups,
  }
}

export interface WordDetailApiState {
  status: WordDetailStatus
  detail: WordDetailPresentation | null
  /** 被解析出的 word（nav param / search fallback）；無則 null。 */
  word: string | null
  retry: () => void
}

/** 解析 shell 路徑欲顯示的 word：nav.params.word 優先、?word= search fallback。 */
export function useWordParam(): string | null {
  const nav = useShellNav()
  if (nav.params.word) return nav.params.word
  return new URLSearchParams(window.location.search).get('word')
}

export function useWordDetailApiStore(word: string | null): WordDetailApiState {
  const api = useApi()
  const [status, setStatus] = useState<WordDetailStatus>('loading')
  const [detail, setDetail] = useState<WordDetailPresentation | null>(null)

  const load = useCallback(async () => {
    if (!word) {
      setStatus('error')
      return
    }
    setStatus('loading')
    try {
      const card = await api.vocabulary.detail(word)
      setDetail(toWordDetail(card))
      setStatus('ready')
    } catch {
      setStatus('error')
    }
  }, [api, word])

  useEffect(() => {
    load()
  }, [load])

  return { status, detail, word, retry: load }
}
