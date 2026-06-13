import { useCallback, useEffect, useState } from 'react'
import { useApi } from '../../api/ApiContext'
import { useShellNav } from '../../shell/ShellNavContext'
import type { CardResponse, VocabContentPatch } from '../../api/types'

/**
 * WordEdit 的 API store — shell=1 時取代 fixture。從 GET /api/vocab/{word} 載入
 * 當前內容，提供翻譯（meaning）/ 教學筆記（explanation→note）兩欄草稿編輯，
 * 並以 PATCH /api/vocab/{word} 樂觀儲存 + 失敗回滾。
 *
 * 樂觀 + 回滾語意：save 時先以草稿值更新 committed（樂觀），呼叫 updateContent；
 * 成功 → committed 採用伺服器回傳；失敗 → committed 與草稿一併回滾至儲存前的值，
 * 並標記 error（使用者可重試）。
 */

export type WordEditStatus = 'loading' | 'ready' | 'error'
export type WordEditSaveState = 'idle' | 'saving' | 'saved' | 'error'

/** 編輯內容的兩欄草稿（鏡射 iOS WordEditSheet：翻譯 + 教學筆記）。 */
export interface WordEditDraft {
  /** 翻譯結果 = card.meaning。 */
  meaning: string
  /** 教學筆記 = card.note（後端 explanation 折進 note）。 */
  explanation: string
}

/** 純函式：CardResponse → 編輯草稿初值。匯出供測試。 */
export function draftFromCard(card: CardResponse): WordEditDraft {
  return { meaning: card.meaning, explanation: card.note ?? '' }
}

/**
 * 純函式：把草稿 diff 成最小 patch（只送有變動的欄位）。explanation 走 patch.note
 * （與 mock/後端契約一致：explanation 折進 note）。匯出供測試。
 */
export function buildContentPatch(orig: WordEditDraft, draft: WordEditDraft): VocabContentPatch {
  const patch: VocabContentPatch = {}
  if (draft.meaning !== orig.meaning) patch.meaning = draft.meaning
  if (draft.explanation !== orig.explanation) patch.note = draft.explanation
  return patch
}

export interface WordEditApiState {
  status: WordEditStatus
  saveState: WordEditSaveState
  word: string | null
  draft: WordEditDraft
  /** 是否有未儲存變動（草稿 != committed）。 */
  isDirty: boolean
  setMeaning: (v: string) => void
  setExplanation: (v: string) => void
  save: () => void
  retry: () => void
}

/** 解析 shell 路徑欲編輯的 word：nav.params.word 優先、?word= search fallback。 */
export function useWordParam(): string | null {
  const nav = useShellNav()
  if (nav.params.word) return nav.params.word
  return new URLSearchParams(window.location.search).get('word')
}

const EMPTY_DRAFT: WordEditDraft = { meaning: '', explanation: '' }

export function useWordEditApiStore(word: string | null): WordEditApiState {
  const api = useApi()
  const [status, setStatus] = useState<WordEditStatus>('loading')
  const [saveState, setSaveState] = useState<WordEditSaveState>('idle')
  // committed = 已落地的值（樂觀更新後採用；失敗回滾的目標）。
  const [committed, setCommitted] = useState<WordEditDraft>(EMPTY_DRAFT)
  const [draft, setDraft] = useState<WordEditDraft>(EMPTY_DRAFT)

  const load = useCallback(async () => {
    if (!word) {
      setStatus('error')
      return
    }
    setStatus('loading')
    try {
      const card = await api.vocabulary.detail(word)
      const d = draftFromCard(card)
      setCommitted(d)
      setDraft(d)
      setStatus('ready')
    } catch {
      setStatus('error')
    }
  }, [api, word])

  useEffect(() => {
    load()
  }, [load])

  const isDirty = draft.meaning !== committed.meaning || draft.explanation !== committed.explanation

  const save = useCallback(() => {
    if (!word) return
    const patch = buildContentPatch(committed, draft)
    if (Object.keys(patch).length === 0) {
      setSaveState('saved')
      return
    }
    const rollback = committed
    const optimistic = draft
    // 樂觀：committed 先採用草稿值。
    setCommitted(optimistic)
    setSaveState('saving')
    api.vocabulary
      .updateContent(word, patch)
      .then((card) => {
        const persisted = draftFromCard(card)
        setCommitted(persisted)
        setDraft(persisted)
        setSaveState('saved')
      })
      .catch(() => {
        // 回滾：committed 與草稿一併還原至儲存前值。
        setCommitted(rollback)
        setDraft(rollback)
        setSaveState('error')
      })
  }, [api, word, committed, draft])

  return {
    status,
    saveState,
    word,
    draft,
    isDirty,
    setMeaning: (v) => {
      setDraft((d) => ({ ...d, meaning: v }))
      setSaveState('idle')
    },
    setExplanation: (v) => {
      setDraft((d) => ({ ...d, explanation: v }))
      setSaveState('idle')
    },
    save,
    retry: load,
  }
}
