/**
 * Live Reader 取詞→翻譯→存詞迴圈的純邏輯（Phase 3）。
 *
 * 把「API response → panel data」「saved words → highlight CSS」「book → 綁定
 * 單字本」「settings ↔ user config」抽成無副作用純函式，令迴圈可單元測試、令
 * `LiveReaderScreen` 只負責 wiring（useApi / state / epub.js）。
 *
 * 對齊 iOS（docs/reference/feature_boundary/reader.md）：
 *   - 單字翻譯走 `/api/translate/quick`（t/p/r），展開語境走 `/api/translate/explain`（e）。
 *   - 存詞走 `/api/vocab`（VocabEntry{word,translation,context,source:'reader'}），
 *     target 綁定單字本（book.preferredNotebookId → notebook_id，fallback default）。
 *   - 已存詞於內文 highlight（iOS `__markVocabWord`；web 以注入 CSS 重現）。
 */

import type {
  ExplainResponse,
  QuickTranslateResponse,
  UserConfigResponse,
} from '../../api/types'
import type { TranslationPanelData } from '../reader/fixtures'
import {
  DEFAULT_SETTINGS,
  FONT_SIZE_MAX,
  FONT_SIZE_MIN,
  type LiveFont,
  type LiveReaderSettings,
} from './liveSettings'

/** Reader 主題（紙色）— 對齊 iOS ReaderSettings theme；phase-3 兩檔。 */
export type LiveTheme = 'paper' | 'dark'
export const DEFAULT_THEME: LiveTheme = 'paper'

/** loading 態 panel（hero 立刻顯示詞，body 顯示翻譯中）。 */
export function loadingPanel(word: string): TranslationPanelData {
  return {
    word,
    partOfSpeech: null,
    translation: null,
    isExpanded: false,
    explanation: null,
    isExplanationOnly: false,
    isPanelLarge: false,
    translationError: null,
    explanationError: null,
    isLoading: true,
    statusMessage: '翻譯中…',
    isSaved: false,
    timerText: null,
  }
}

/**
 * QuickTranslateResponse（t/p/r）→ 已完成 panel。p（發音）目前無 panel 欄位承載，
 * r（lemma）保留給存詞 root_form；此處只投影 translation。
 */
export function resolvedPanel(
  word: string,
  res: QuickTranslateResponse,
  opts: { isSaved?: boolean } = {},
): TranslationPanelData {
  return {
    word,
    partOfSpeech: null,
    translation: res.t,
    isExpanded: false,
    explanation: null,
    isExplanationOnly: false,
    isPanelLarge: false,
    translationError: null,
    explanationError: null,
    isLoading: false,
    statusMessage: null,
    isSaved: opts.isSaved ?? false,
    timerText: null,
  }
}

/** 翻譯失敗 → error panel（取代譯文的 state message card）。 */
export function errorPanel(word: string, message: string): TranslationPanelData {
  return {
    word,
    partOfSpeech: null,
    translation: null,
    isExpanded: false,
    explanation: null,
    isExplanationOnly: false,
    isPanelLarge: false,
    translationError: message,
    explanationError: null,
    isLoading: false,
    statusMessage: null,
    isSaved: false,
    timerText: null,
  }
}

/** 展開語境解釋（ExplainResponse.e）→ 在現有 panel 上疊解釋段。 */
export function withExplanation(
  panel: TranslationPanelData,
  res: ExplainResponse,
): TranslationPanelData {
  return { ...panel, isExpanded: true, explanation: res.e, explanationError: null }
}

/** 展開語境解釋失敗 → 在現有 panel 上掛 explanationError（仍展開）。 */
export function withExplanationError(
  panel: TranslationPanelData,
  message: string,
): TranslationPanelData {
  return { ...panel, isExpanded: true, explanationError: message }
}

/** 折疊語境解釋（再點 chevron）。 */
export function collapseExplanation(panel: TranslationPanelData): TranslationPanelData {
  return { ...panel, isExpanded: false }
}

/** 標記 panel 為「已加入」（footer green check）。 */
export function markSaved(panel: TranslationPanelData): TranslationPanelData {
  return { ...panel, isSaved: true }
}

/**
 * 解析本書綁定單字本：book.notebook_id 優先，否則 fallback default。
 * 對齊 iOS `book.resolvedNotebookId`（綁定本 → 全域 fallback）。
 */
export function resolveBoundNotebookId(
  bookNotebookId: string | null | undefined,
  defaultNotebookId: string,
): string {
  return bookNotebookId ?? defaultNotebookId
}

/** 詞正規化（小寫 + 去頭尾標點）— highlight 命中與去重用。 */
export function normalizeWord(word: string): string {
  return word.toLowerCase().replace(/^['-]+|['-]+$/g, '').trim()
}

/**
 * 已存詞集合 → 注入內文 iframe 的 highlight CSS（iOS `__markVocabWord` 的 web 對應）。
 * epub.js 把每個 section 渲染進 iframe；我們無法在純 CSS 裡選「含某詞的文字節點」，
 * 故此函式產出的是 highlight 的「樣式定義」（底線 + 低彩底色），實際命中標記由
 * 呼叫端在 section document 上以 <mark class="kg-vocab-hl"> 包裹命中詞完成。
 * 樣式對齊 iOS VocabHighlightPreferences（底線色 + 低 opacity band）。
 */
export function highlightCss(): string {
  return `mark.kg-vocab-hl{background:rgba(175,194,211,0.32) !important;color:inherit !important;border-radius:2px;padding:0 1px;box-decoration-break:clone;-webkit-box-decoration-break:clone;}`
}

/** 已存詞集合 → 用於 section 內標記的正規化詞 set。 */
export function highlightWordSet(savedWords: Iterable<string>): Set<string> {
  const set = new Set<string>()
  for (const w of savedWords) {
    const n = normalizeWord(w)
    if (n.length >= 2) set.add(n)
  }
  return set
}

// ── settings ↔ user config ────────────────────────────────────────────────
// Reader font/theme 在 iOS 走本機 @AppStorage（ReaderSettings.swift），後端
// UserConfigResponse 不含對應欄位。web 把它折進 `vocab_ui` 這個 opaque bag 的
// `reader` 命名空間（forward-declared client 契約，mock echo-merge 相容），避免
// 發明新的後端欄位；待後端真有 reader-settings face 再遷移。

const READER_CFG_KEY = 'reader'

interface ReaderSettingsConfig {
  fontSize?: unknown
  font?: unknown
  theme?: unknown
}

/** 從 UserConfigResponse 還原 reader 設定（缺欄或越界 → 預設，永不丟例外）。 */
export function settingsFromConfig(
  config: UserConfigResponse | null | undefined,
): { settings: LiveReaderSettings; theme: LiveTheme } {
  const bag = (config?.vocab_ui ?? {}) as Record<string, unknown>
  const raw = (bag[READER_CFG_KEY] ?? {}) as ReaderSettingsConfig
  const fontSize =
    typeof raw.fontSize === 'number' &&
    raw.fontSize >= FONT_SIZE_MIN &&
    raw.fontSize <= FONT_SIZE_MAX
      ? raw.fontSize
      : DEFAULT_SETTINGS.fontSize
  const font: LiveFont = raw.font === 'sans' || raw.font === 'serif' ? raw.font : DEFAULT_SETTINGS.font
  const theme: LiveTheme = raw.theme === 'dark' || raw.theme === 'paper' ? raw.theme : DEFAULT_THEME
  return { settings: { fontSize, font }, theme }
}

/** 把 reader 設定投影成 PUT /api/user/config 的 partial（只動 vocab_ui.reader）。 */
export function configPatchFromSettings(
  settings: LiveReaderSettings,
  theme: LiveTheme,
  existingVocabUi: UserConfigResponse['vocab_ui'],
): { vocab_ui: Record<string, unknown> } {
  const base = (existingVocabUi ?? {}) as Record<string, unknown>
  return {
    vocab_ui: {
      ...base,
      [READER_CFG_KEY]: { fontSize: settings.fontSize, font: settings.font, theme },
    },
  }
}
