import { useCallback, useEffect, useState } from 'react'
import { useApi } from '../../api/ApiContext'
import { useShellNav } from '../../shell/ShellNavContext'
import type { CardLinkSummaryResponse, CardResponse } from '../../api/types'

/**
 * LinkedCardOverlayStack 的 API store — shell=1 時取代「載入中」placeholder，
 * 從 GET /api/vocab/{word} 取來源卡，把 linksByKind 攤平成依 kind 字母序的群組，
 * 在 overlay 卡內渲染各連結（word + reason），過濾 hidden link。
 *
 * 誠實邊界：word 來源 = ShellNavContext.params.word 優先、?word= search fallback。
 * parity 路徑（無 shell）不呼叫此 hook，DOM 與 capture 完全不變。
 */

export type LinkedCardStatus = 'loading' | 'ready' | 'error'

export interface LinkedCardGroup {
  kind: string
  label: string
  links: CardLinkSummaryResponse[]
}

/** 純函式：linksByKind → 依 kind 字母序、過濾 hidden 的群組陣列。匯出供測試。 */
export function toLinkGroups(card: CardResponse): LinkedCardGroup[] {
  return Object.entries(card.linksByKind)
    .map(([kind, links]) => {
      const visible = links.filter((l) => !l.hidden)
      return { kind, label: visible[0]?.label ?? kind, links: visible }
    })
    .filter((g) => g.links.length > 0)
    .sort((a, b) => (a.kind < b.kind ? -1 : a.kind > b.kind ? 1 : 0))
}

export interface VocabLinkedCardApiState {
  status: LinkedCardStatus
  word: string | null
  groups: LinkedCardGroup[]
  retry: () => void
}

export function useVocabLinkedCardApiStore(): VocabLinkedCardApiState {
  const api = useApi()
  const nav = useShellNav()
  const word = nav.params.word ?? new URLSearchParams(window.location.search).get('word')

  const [status, setStatus] = useState<LinkedCardStatus>('loading')
  const [groups, setGroups] = useState<LinkedCardGroup[]>([])

  const load = useCallback(async () => {
    if (!word) {
      setStatus('error')
      return
    }
    setStatus('loading')
    try {
      const card = await api.vocabulary.detail(word)
      setGroups(toLinkGroups(card))
      setStatus('ready')
    } catch {
      setStatus('error')
    }
  }, [api, word])

  useEffect(() => {
    load()
  }, [load])

  return { status, word, groups, retry: load }
}
