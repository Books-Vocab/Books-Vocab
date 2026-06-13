import type { ScenarioId } from '../../harness/scenarios'

/**
 * Reader R3 面板群 fixtures — TOC / Settings / Notebook Picker。
 *
 * SoT：
 *   TOC      — ios/.../Debug/Scenarios/ReaderScenarios.swift · "Reader · TOC"（4 態）
 *              + ios/.../Views/Reader/TOCView.swift（TOCViewPreviewScene）。
 *   Settings — ReaderScenarios.swift · "Reader · Settings"（Normal / Bounds(min) /
 *              Bounds(max)，bounds-max = PR #929）+ ReaderSettingsPresenter+Vocab.swift。
 *   Notebook — ReaderNotebookPickerScenarios.swift + NotebookBindingList.swift。
 *
 * Notebook 對拍策略（2026-06-11 更新，與 R1 一致）：web 是 **catalog snapshot 的像素
 * 重建**，非 live app。對拍 ref = catalog-full-20260611-130335，已含 2026-06-09 的
 * NotebookBindingList strict-binding 改版（commit 1d23758d 移除 follow-global 列 +
 * 每列「預設」副標）。故 web 已隨之收斂至 strict-binding 形態：**無**頂部「跟隨全域
 * 設定」卡、**無** isDefault「預設」副標，僅 section header「單字本」+ insetGrouped
 * 列（色條 + 名稱 + 綁定列 accent checkmark）。`isDefault` 欄位保留於 fixture data
 * 僅為對齊 iOS sampleNotebooks seed，渲染面不再消費。 */

// ============================================================
// TOC
// ============================================================

export type TocState = 'loading' | 'loaded' | 'empty' | 'failed'

export interface TocFixture {
  state: TocState
  /** loaded 時的章節標題（ReaderScenarios "Loaded" seed）。 */
  chapters: string[]
  /** failed 時的錯誤訊息（ReaderScenarios "Failed" seed）。 */
  failedMessage: string
}

const TOC_CHAPTERS = ['第一章', '第二章', '第三章', '第四章', '第五章']
const TOC_FAILED_MESSAGE = 'Publication manifest 解析失敗。'

// ============================================================
// Settings
// ============================================================

export interface SettingsFixture {
  /** 字級顯示文字（state.fontSizeText）。 */
  fontSizeText: string
  /** 小 A stepper 是否可用（false = 灰化）。 */
  canDecreaseFontSize: boolean
  /** 大 A stepper 是否可用（false = 灰化）。 */
  canIncreaseFontSize: boolean
}

// 行距 1.5 / font serif(Garamond) / theme sepia / underline 中(0.35) / 翻頁模式
// —— 對齊 ReaderSettingsPanelPreviewHarness 預設 @State（PNG 實測一致）。
export const SETTINGS_LINE_HEIGHT = 1.5
export const SETTINGS_FONT_LABEL = 'Garamond'
export const SETTINGS_FONT_TONE = 'classic'
/** ReaderTheme.allCases 順序：light / sepia / dark。selected = sepia。
 *  swatch bar 色 = readerThemeSwatchColor（PNG 實測 ÷255 hex）。 */
export const SETTINGS_THEMES: { label: string; swatch: string; icon: 'sun' | 'book' | 'moon' }[] = [
  { label: 'Light', swatch: '#f2f1ee', icon: 'sun' },
  { label: 'Sepia', swatch: '#d1ba94', icon: 'book' },
  { label: 'Dark', swatch: '#2e2e2e', icon: 'moon' },
]
export const SETTINGS_SELECTED_THEME = 'Sepia'
/** 生字標記顏色 4 swatch（VocabHighlightColorPreset 順序，PNG 實測）。selected = 紙色。 */
export const SETTINGS_COLOR_SWATCHES: { label: string; hex: string }[] = [
  { label: '紙色', hex: '#e6d691' },
  { label: '藍色', hex: '#4c7396' },
  { label: '鼠尾草', hex: '#6b9169' },
  { label: '玫瑰', hex: '#b37385' },
]
export const SETTINGS_SELECTED_COLOR = '紙色'

// ============================================================
// Notebook Picker
// ============================================================

export interface NotebookEntry {
  remoteId: string
  name: string
  /** notebook.color（hex）或 null（落 accent）。 */
  color: string | null
  /** isDefault → 列下顯示「預設」副標（對齊 snapshot 像素）。 */
  isDefault: boolean
}

export interface NotebookFixture {
  notebooks: NotebookEntry[]
  /** 選中（綁定）的 notebook remoteId，或 null（= 跟隨全域，follow-global 卡被勾）。 */
  boundRemoteId: string | null
}

// ReaderNotebookPickerScene.sampleNotebooks（color: nil 落 accent；isDefault → 預設副標）。
const SAMPLE_NOTEBOOKS: NotebookEntry[] = [
  { remoteId: 'nb-default', name: '我的單字本', color: null, isDefault: true },
  { remoteId: 'nb-green', name: '綠野仙蹤生詞', color: '#2E8B57', isDefault: false },
  { remoteId: 'nb-blue', name: '商業英文', color: '#3B6FD4', isDefault: false },
]

// ReaderNotebookPickerScene.manyNotebooks（1...14，palette rotate；#1 isDefault）。
const MANY_PALETTE = ['#E0533B', '#2E8B57', '#3B6FD4', '#C9A227', '#7A4FD0']
const MANY_NOTEBOOKS: NotebookEntry[] = Array.from({ length: 14 }, (_, i) => {
  const n = i + 1
  return {
    remoteId: `nb-${n}`,
    name: `單字本 #${n} — 長標題測試截斷行為的範例文字`,
    color: MANY_PALETTE[n % MANY_PALETTE.length],
    isDefault: n === 1,
  }
})

// ============================================================
// Panel kind discrimination（依 scenario id 前綴路由）
// ============================================================

export type ReaderPanelKind = 'toc' | 'settings' | 'notebook'

/** scenario id 前綴 → 面板種類；非面板 scenario（chrome）回 null。 */
export function readerPanelKind(scenario: ScenarioId<'reader'>): ReaderPanelKind | null {
  if (scenario.startsWith('toc-')) return 'toc'
  if (scenario.startsWith('settings-')) return 'settings'
  if (scenario.startsWith('notebook-')) return 'notebook'
  return null
}

export const TOC_FIXTURES: Partial<Record<ScenarioId<'reader'>, TocFixture>> = {
  'toc-loaded': { state: 'loaded', chapters: TOC_CHAPTERS, failedMessage: '' },
  'toc-loading': { state: 'loading', chapters: [], failedMessage: '' },
  'toc-empty': { state: 'empty', chapters: [], failedMessage: '' },
  'toc-failed': { state: 'failed', chapters: [], failedMessage: TOC_FAILED_MESSAGE },
}

export const SETTINGS_FIXTURES: Partial<Record<ScenarioId<'reader'>, SettingsFixture>> = {
  'settings-normal': { fontSizeText: '1.0x', canDecreaseFontSize: true, canIncreaseFontSize: true },
  'settings-bounds-min': { fontSizeText: '0.75x', canDecreaseFontSize: false, canIncreaseFontSize: true },
  'settings-bounds-max': { fontSizeText: '2.0x', canDecreaseFontSize: true, canIncreaseFontSize: false },
}

export const NOTEBOOK_FIXTURES: Partial<Record<ScenarioId<'reader'>, NotebookFixture>> = {
  'notebook-follow-global': { notebooks: SAMPLE_NOTEBOOKS, boundRemoteId: null },
  'notebook-one-bound': { notebooks: SAMPLE_NOTEBOOKS, boundRemoteId: 'nb-green' },
  'notebook-stress': { notebooks: MANY_NOTEBOOKS, boundRemoteId: 'nb-12' },
  'notebook-empty': { notebooks: [], boundRemoteId: null },
}
