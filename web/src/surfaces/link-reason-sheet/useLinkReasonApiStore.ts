import { useCallback, useEffect, useState } from 'react'
import { useApi } from '../../api/ApiContext'
import { useShellNav } from '../../shell/ShellNavContext'
import type { CardLinkSummaryResponse, CardResponse } from '../../api/types'

/**
 * LinkReasonSheet 的 API store — shell=1 時取代 fixture。從 GET /api/vocab/{word}
 * 取來源卡，於 linksByKind 找出目標 link（params.linkId），顯示其 label/word/reason
 * 並提供 hide / unhide（PATCH /api/graph/links/{id}/hide|unhide，204）。
 *
 * 誠實邊界：word / linkId / notebookId 來源 = ShellNavContext.params 優先、
 * window.location.search fallback。linkId 經 ScreenParams 的 word 槽不足以承載，
 * 故額外讀 ?link_id= search（nav 端若需要可同走 search）。parity 路徑不呼叫此 hook。
 */

export type LinkReasonStatus = 'loading' | 'ready' | 'error'

/** 純函式：於卡片的 linksByKind 找出指定 id 的 link summary。匯出供測試。 */
export function findLinkSummary(card: CardResponse, linkId: string): CardLinkSummaryResponse | null {
  for (const links of Object.values(card.linksByKind)) {
    const hit = links.find((l) => l.id === linkId)
    if (hit) return hit
  }
  return null
}

export interface LinkReasonApiState {
  status: LinkReasonStatus
  link: CardLinkSummaryResponse | null
  /** 當前是否隱藏（樂觀）。 */
  hidden: boolean
  toggleHidden: () => void
  retry: () => void
}

export function useLinkReasonApiStore(): LinkReasonApiState {
  const api = useApi()
  const nav = useShellNav()
  const search = new URLSearchParams(window.location.search)
  const word = nav.params.word ?? search.get('word')
  const linkId = search.get('link_id')
  const notebookId = nav.params.notebookId ?? search.get('notebook_id') ?? undefined

  const [status, setStatus] = useState<LinkReasonStatus>('loading')
  const [link, setLink] = useState<CardLinkSummaryResponse | null>(null)
  const [hidden, setHidden] = useState(false)

  const load = useCallback(async () => {
    if (!word || !linkId) {
      setStatus('error')
      return
    }
    setStatus('loading')
    try {
      const card = await api.vocabulary.detail(word)
      const summary = findLinkSummary(card, linkId)
      if (!summary) {
        setStatus('error')
        return
      }
      setLink(summary)
      setHidden(summary.hidden)
      setStatus('ready')
    } catch {
      setStatus('error')
    }
  }, [api, word, linkId])

  useEffect(() => {
    load()
  }, [load])

  const toggleHidden = useCallback(() => {
    if (!linkId) return
    const next = !hidden
    setHidden(next) // 樂觀
    const call = next
      ? api.graph.hide(linkId, notebookId ? { notebookId } : {})
      : api.graph.unhide(linkId, notebookId ? { notebookId } : {})
    call.catch(() => setHidden(!next)) // 失敗回滾
  }, [api, hidden, linkId, notebookId])

  return { status, link, hidden, toggleHidden, retry: load }
}
