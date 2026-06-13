import { useCallback, useEffect, useState } from 'react'
import { useApi } from '../../api/ApiContext'
import { useShellNav } from '../../shell/ShellNavContext'

/**
 * CollocationExplainSheet 的 API store — shell=1 時取代 fixture。把 nav 帶進來的
 * collocation（params.word）丟給 POST /api/translate/explain（quota-gated LLM，
 * mock 立即回 ExplainResponse.e），鏡射 iOS `CollocationExplainSheet` 的 .loaded
 * 流程：sheet 開啟 → 無 existingExplanation 時即時翻譯出 explanation。
 *
 * 誠實邊界：collocation 來源 = ShellNavContext.params.word 優先、?word= search
 * fallback；context（搭配所屬例句）讀 ?context= search（nav 端若需要可同走 search）。
 * parity 路徑（無 shell）不呼叫此 hook，DOM 與 capture 完全不變。
 */

export type CollocationExplainStatus = 'loading' | 'ready' | 'error'

export interface CollocationExplainApiState {
  status: CollocationExplainStatus
  /** 被解釋的搭配詞（標題顯示）；無則 null。 */
  collocation: string | null
  /** LLM 回傳的解釋文（ExplainResponse.e）；非 ready 時為空字串。 */
  explanation: string
  retry: () => void
}

export function useCollocationExplainApiStore(): CollocationExplainApiState {
  const api = useApi()
  const nav = useShellNav()
  const search = new URLSearchParams(window.location.search)
  const collocation = nav.params.word ?? search.get('word')
  const context = search.get('context') ?? undefined

  const [status, setStatus] = useState<CollocationExplainStatus>('loading')
  const [explanation, setExplanation] = useState('')

  const load = useCallback(async () => {
    if (!collocation) {
      setStatus('error')
      return
    }
    setStatus('loading')
    try {
      const res = await api.translate.explain({ word: collocation, context })
      setExplanation(res.e)
      setStatus('ready')
    } catch {
      setStatus('error')
    }
  }, [api, collocation, context])

  useEffect(() => {
    load()
  }, [load])

  return { status, collocation: collocation ?? null, explanation, retry: load }
}
