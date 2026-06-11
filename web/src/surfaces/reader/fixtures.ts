import type { ScenarioId } from '../../harness/scenarios'

/**
 * Reader surface fixtures — mirrors iOS Catalog "Reader View · Chrome"
 * (ReaderChromeScenarios.swift). 每個 scenario 純由 ReaderViewPresenterState
 * 驅動：paper 色、loadingPhase、underlineProgress、header 形態、totalProgression
 * 皆對齊 Catalog seed。本體（page body）一律是 synthetic paper（8 placeholder
 * blocks）——無 live publication / WKWebView。
 *
 * 設計軸取捨（已拍板）：reader paper 永遠是 sepia 調，與全域 light/dark
 * appearance 軸正交。paper 色（paperSepia vs paperSepiaDeep）是 *scenario* 維度，
 * 直接帶在 fixture 上；chrome（白卡、文字色）才吃 data-theme。
 */

/** AppColors paper tones（iOS SoT，rgb→hex）：
 *  paperSepia     = rgb(0.98, 0.965, 0.94)  → #faf6f0
 *  paperSepiaDeep = rgb(0.96, 0.93, 0.87)   → #f5edde
 *  warmNeutral    = hsb(30°, 0.18, 0.62)    → #9e9082（gradient floor 用） */
export const PAPER_SEPIA = '#faf6f0'
export const PAPER_SEPIA_DEEP = '#f5edde'
export const WARM_NEUTRAL = '#9e9082'

/** header 形態 — 對齊 iOS ReaderChromeState.header。 */
export type ReaderHeader = 'compact' | 'expanded'
/** bottom overlay 形態 — translation 是 R2 scope，本刀只佔位（chrome 不變）。 */
export type ReaderOverlay = 'none' | 'translation'

export interface ReaderFixture {
  /** state.paperColor — 本體 gradient 起始色（top/mid），floor 固定 warmNeutral。 */
  paperColor: string
  /** state.isWebViewReady — false 時疊置中 loading 卡。 */
  isWebViewReady: boolean
  /** state.loadingPhase — loading 卡的階段文字。 */
  loadingPhase: string
  /** state.underlineProgress（0–1 或 null）— 非 null 時頂部疊 underline 進度卡。 */
  underlineProgress: number | null
  header: ReaderHeader
  overlay: ReaderOverlay
  /** state.totalProgression（0–1）— compact 進度膠囊只在 > 0 時顯示。 */
  totalProgression: number
  bookTitle: string
  /** 顯示「無法開啟書籍」error 卡（取代本體 placeholder blocks）。 */
  showsErrorCard: boolean
}

/** ReaderChromeScenarios.swift 6 態，逐欄對齊 catalog seed。 */
export const READER_FIXTURES: Record<ScenarioId<'reader'>, ReaderFixture> = {
  // Loading · Render — paperSepiaDeep；isWebViewReady=false（置中 loading 卡）+
  // underlineProgress=0.42（頂部進度卡）；compact header（18.0% 膠囊）。
  'loading-render': {
    paperColor: PAPER_SEPIA_DEEP,
    isWebViewReady: false,
    loadingPhase: '渲染頁面…',
    underlineProgress: 0.42,
    header: 'compact',
    overlay: 'none',
    totalProgression: 0.18,
    bookTitle: 'The Left Hand of Darkness',
    showsErrorCard: false,
  },
  // Loading · Mark Vocab — paperSepia；loading 卡「標記生字…」+ underline 0.68。
  'loading-vocab': {
    paperColor: PAPER_SEPIA,
    isWebViewReady: false,
    loadingPhase: '標記生字…',
    underlineProgress: 0.68,
    header: 'compact',
    overlay: 'none',
    totalProgression: 0.18,
    bookTitle: 'The Left Hand of Darkness',
    showsErrorCard: false,
  },
  // Reading · Compact Header — paperSepia；ready，compact 膠囊 37.0% + ellipsis。
  'reading-compact': {
    paperColor: PAPER_SEPIA,
    isWebViewReady: true,
    loadingPhase: '開啟書本…',
    underlineProgress: null,
    header: 'compact',
    overlay: 'none',
    totalProgression: 0.37,
    bookTitle: 'The Left Hand of Darkness',
    showsErrorCard: false,
  },
  // Reading · Expanded Header — paperSepia；flat toolbar（書庫 + 書名 + 4 鈕）。
  'reading-expanded': {
    paperColor: PAPER_SEPIA,
    isWebViewReady: true,
    loadingPhase: '開啟書本…',
    underlineProgress: null,
    header: 'expanded',
    overlay: 'none',
    totalProgression: 0.81,
    bookTitle: 'The Left Hand of Darkness',
    showsErrorCard: false,
  },
  // Reading · Translation Overlay — paperSepiaDeep；compact + translation overlay。
  // panel 本體屬 R2，本刀只還原其後 chrome（compact 膠囊 37.0%）。
  'reading-translation': {
    paperColor: PAPER_SEPIA_DEEP,
    isWebViewReady: true,
    loadingPhase: '開啟書本…',
    underlineProgress: null,
    header: 'compact',
    overlay: 'translation',
    totalProgression: 0.37,
    bookTitle: 'The Left Hand of Darkness',
    showsErrorCard: false,
  },
  // Error · Open Failed — paperSepiaDeep；totalProgression=0（膠囊隱藏，僅 ellipsis）+
  // 置中「無法開啟書籍」卡。
  'error-open-failed': {
    paperColor: PAPER_SEPIA_DEEP,
    isWebViewReady: true,
    loadingPhase: '開啟書本…',
    underlineProgress: null,
    header: 'compact',
    overlay: 'none',
    totalProgression: 0,
    bookTitle: 'The Left Hand of Darkness',
    showsErrorCard: true,
  },
}
