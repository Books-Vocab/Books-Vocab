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
/** bottom overlay 形態 — translation 疊 TranslationPanel（R2）。 */
export type ReaderOverlay = 'none' | 'translation'

/** ReaderSkin translation brown（iOS SoT）：
 *  translationLight = rgb(0.54, 0.50, 0.44) = #8a8070（serif 譯文色）。 */
export const TRANSLATION_BROWN = '#8a8070'

/**
 * TranslationPanel 內容態 — 鏡像 TranslationPanelPresenterState.contentMode ×
 * explanationContentMode（TranslationPanelPresenter+State.swift）。
 * iPhone = .bottomSheet：drag handle、contentTopInset=0、bottom-flush。
 *   - translation：hero 譯文（+ 可選 explanation 段）+ footer chevron
 *   - explanationOnly：純 explanation 段（無 hero 譯文、無 chevron）
 *   - loading / translationError / explanationError：state message card
 */
export interface TranslationPanelData {
  word: string
  /** 詞性 chip（adj. 等）；null 隱藏。 */
  partOfSpeech: string | null
  /** 譯文（serif brown）；loading/error/explainOnly 時為 null。 */
  translation: string | null
  /** 展開語境解釋（divider + 「語境解釋」label + body / loading / error）。 */
  isExpanded: boolean
  explanation: string | null
  /** 句子模式：純解釋、無譯文 hero、footer 出高度切換鈕（chevron up/down）。 */
  isExplanationOnly: boolean
  /** 大卡（撐高 0.84 viewport）— 句子展開態。 */
  isPanelLarge: boolean
  /** 翻譯失敗：取代譯文的 state message card（「翻譯暫時失敗」+ desc）。 */
  translationError: string | null
  /** 語境解釋失敗：explanation 段內的 error message card。 */
  explanationError: string | null
  /** 整體 loading（翻譯中）：取代 body 的 loading state card。 */
  isLoading: boolean
  /** 狀態文字（loading 卡標題覆寫）；null 用預設「翻譯中...」。 */
  statusMessage: string | null
  /** footer「已加入」green check（isSaved && isLoggedIn）。 */
  isSaved: boolean
  /** footer timer（0.0s 等）；null 隱藏。 */
  timerText: string | null
}

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
  /** overlay==='translation' 時疊在 reader 本體上的 panel 內容（含 scrim）；
   *  其餘態為 null（無 panel）。 */
  panel: TranslationPanelData | null
}

/** chrome 6 態 id（reader surface 扣掉 translation-* 後的子集）。 */
export type ReaderChromeScenarioId = Exclude<ScenarioId<'reader'>, TranslationScenarioId>

/** ReaderChromeScenarios.swift 6 態，逐欄對齊 catalog seed。 */
export const READER_FIXTURES: Record<ReaderChromeScenarioId, ReaderFixture> = {
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
    panel: null,
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
    panel: null,
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
    panel: null,
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
    panel: null,
  },
  // Reading · Translation Overlay — paperSepiaDeep；compact + translation overlay。
  // R2：panel（resilient，expanded）疊在 dimmed paper 上。對拍 ref =
  // Reader View · Chrome / Reading · Translation Overlay（word resilient）。
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
    panel: {
      word: 'resilient',
      partOfSpeech: 'adj.',
      translation: '有韌性的；能快速恢復的',
      isExpanded: true,
      explanation: '在這段語境中指角色面對壓力後仍迅速回到穩定狀態。',
      isExplanationOnly: false,
      isPanelLarge: false,
      translationError: null,
      explanationError: null,
      isLoading: false,
      statusMessage: null,
      isSaved: true,
      timerText: '0.0s',
    },
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
    panel: null,
  },
}

/**
 * 獨立 Translation panel 6 態（layout .fill = scrim + bottom-sheet panel，無
 * reader 本體）。逐欄對齊 ReaderScenarios.swift「Reader · Translation」+
 * TranslationPanelPreviewScene（word gorgeous / adj. / 譯文「華麗的；令人驚豔的」）。
 */
export type TranslationScenarioId =
  | 'translation-expanded'
  | 'translation-collapsed'
  | 'translation-loading'
  | 'translation-error'
  | 'translation-explain-only'
  | 'translation-explanation-error'

const GORGEOUS_TRANSLATION = '華麗的；令人驚豔的'
const GORGEOUS_EXPLANATION =
  '常用來描述外觀、氣氛或令人印象深刻的事物，語氣通常偏正面且帶有審美色彩。'

/** 6 態共用的基線（gorgeous / adj. / isSaved / 0.0s timer），各態覆寫差異欄。 */
function baseGorgeous(): TranslationPanelData {
  return {
    word: 'gorgeous',
    partOfSpeech: 'adj.',
    translation: GORGEOUS_TRANSLATION,
    isExpanded: false,
    explanation: null,
    isExplanationOnly: false,
    isPanelLarge: false,
    translationError: null,
    explanationError: null,
    isLoading: false,
    statusMessage: null,
    isSaved: true,
    timerText: '0.0s',
  }
}

export const TRANSLATION_FIXTURES: Record<TranslationScenarioId, TranslationPanelData> = {
  // Expanded — 譯文 + 展開語境解釋（divider + 「語境解釋」+ body）。harness 預設
  // explanation 文案。footer chevron.up（已展開）。
  'translation-expanded': {
    ...baseGorgeous(),
    isExpanded: true,
    explanation: GORGEOUS_EXPLANATION,
  },
  // Collapsed — 譯文 only，無解釋段；footer chevron.down（可展開）。
  'translation-collapsed': {
    ...baseGorgeous(),
    isExpanded: false,
  },
  // Loading — 翻譯中：取代 body 的 loading state card（translate 圖示 +
  // 「Added to Vocabulary」status + spinner + timer）。無譯文 hero。
  'translation-loading': {
    ...baseGorgeous(),
    translation: null,
    isLoading: true,
    statusMessage: 'Added to Vocabulary',
  },
  // Error — 翻譯失敗：state message card「翻譯暫時失敗」+ desc。footer 無 chevron。
  'translation-error': {
    ...baseGorgeous(),
    translation: null,
    translationError: '翻譯服務逾時，請稍後再試。',
  },
  // Explain Only — 句子模式：純解釋段（無譯文 hero）+ footer 高度切換 chevron。
  // ref scenario isPanelLarge 預設 false（小卡，非撐高）。
  'translation-explain-only': {
    ...baseGorgeous(),
    isExpanded: true,
    isExplanationOnly: true,
    isPanelLarge: false,
    explanation: GORGEOUS_EXPLANATION,
  },
  // Explanation Error — 展開態，譯文在但解釋段顯示 error card。
  'translation-explanation-error': {
    ...baseGorgeous(),
    isExpanded: true,
    explanation: null,
    explanationError: '語境分析暫時不可用。',
  },
}

/** scenario id → 獨立 panel fixture；非 translation-* id 回 null（走 chrome 路徑）。 */
export function translationFixtureFor(scenario: string): TranslationPanelData | null {
  return (TRANSLATION_FIXTURES as Record<string, TranslationPanelData>)[scenario] ?? null
}
