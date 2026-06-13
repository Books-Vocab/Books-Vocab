import { useCallback, useEffect, useState } from 'react'
import { useApi } from '../../api/ApiContext'
import type { TranslationLanguageConfig, UserConfigResponse } from '../../api/types'
import { SOURCE_LANGUAGES, TARGET_LANGUAGES } from './fixtures'

/**
 * TranslationLanguageSettings 的 API store — shell=1 時取代 fixture。
 *
 * 後端 `TranslationLanguageConfig`（api_models/translate.py）為 `/api/user/config`
 * 的 LWW 家族成員，形狀 `{ source_lang, target_lang, updated_at }`（source/target
 * 共用單一 group 時戳）。web 端 type 為 opaque（`[key: string]: unknown`），故在此
 * 以純函式安全投影/組裝那兩個欄位，避免在 view 內散落 cast。
 *
 * 互動：點選語言列即樂觀更新本地選取 + PUT /api/user/config（只送 translation
 * sub-config），失敗回滾。source/target 一起送（對齊 iOS：同 group 一起改、一起
 * 跨裝置 LWW 收斂）。
 */

/** 預設語言對（與 fixtures 的 english-to-traditional-chinese 一致，亦為後端預設）。 */
export const DEFAULT_SOURCE_LANG = 'en'
export const DEFAULT_TARGET_LANG = 'zh-Hant'

const SOURCE_IDS = new Set(SOURCE_LANGUAGES.map((l) => l.id))
const TARGET_IDS = new Set(TARGET_LANGUAGES.map((l) => l.id))

export interface LangSelection {
  sourceId: string
  targetId: string
}

/**
 * 純函式：從 UserConfigResponse 投影出語言對，缺欄位 / 非法值回落預設。
 * 匯出供測試。
 */
export function selectionFromConfig(config: UserConfigResponse | null): LangSelection {
  const t = (config?.translation ?? null) as Record<string, unknown> | null
  const rawSource = t && typeof t.source_lang === 'string' ? t.source_lang : null
  const rawTarget = t && typeof t.target_lang === 'string' ? t.target_lang : null
  return {
    sourceId: rawSource && SOURCE_IDS.has(rawSource) ? rawSource : DEFAULT_SOURCE_LANG,
    targetId: rawTarget && TARGET_IDS.has(rawTarget) ? rawTarget : DEFAULT_TARGET_LANG,
  }
}

/**
 * 純函式：把語言對組裝成 PUT /api/user/config 的 translation patch（單一 group LWW，
 * 不帶時戳 → 由後端蓋時間，對齊既有 settings 寫法）。匯出供測試。
 */
export function buildTranslationPatch(sel: LangSelection): { translation: TranslationLanguageConfig } {
  return {
    translation: {
      source_lang: sel.sourceId,
      target_lang: sel.targetId,
      updated_at: null,
    },
  }
}

export type TranslationLangStatus = 'loading' | 'ready'

export interface TranslationLangApiState {
  status: TranslationLangStatus
  selection: LangSelection
  /** 選閱讀語言（source）。 */
  pickSource: (id: string) => void
  /** 選翻譯語言（target）。 */
  pickTarget: (id: string) => void
}

export function useTranslationLangApiStore(): TranslationLangApiState {
  const api = useApi()
  const [status, setStatus] = useState<TranslationLangStatus>('loading')
  // committed = 已落地的選取（樂觀更新採用；失敗回滾目標）。
  const [committed, setCommitted] = useState<LangSelection>({
    sourceId: DEFAULT_SOURCE_LANG,
    targetId: DEFAULT_TARGET_LANG,
  })
  const [selection, setSelection] = useState<LangSelection>(committed)

  const load = useCallback(async () => {
    setStatus('loading')
    try {
      const cfg = await api.user.config()
      const sel = selectionFromConfig(cfg)
      setCommitted(sel)
      setSelection(sel)
    } catch {
      // 載入失敗：保留預設（不阻塞 UI），仍可互動寫入。
    } finally {
      setStatus('ready')
    }
  }, [api])

  useEffect(() => {
    load()
  }, [load])

  const push = useCallback(
    (next: LangSelection) => {
      if (next.sourceId === committed.sourceId && next.targetId === committed.targetId) return
      const rollback = committed
      // 樂觀：committed 先採用新選取。
      setCommitted(next)
      setSelection(next)
      api.user
        .updateConfig(buildTranslationPatch(next))
        .then((saved) => {
          const persisted = selectionFromConfig(saved)
          setCommitted(persisted)
          setSelection(persisted)
        })
        .catch(() => {
          setCommitted(rollback)
          setSelection(rollback)
        })
    },
    [api, committed],
  )

  return {
    status,
    selection,
    pickSource: (id) => push({ ...selection, sourceId: id }),
    pickTarget: (id) => push({ ...selection, targetId: id }),
  }
}
