/**
 * Live reader 設定模型 — 對齊 iOS `ReaderSettings`（ReaderSettings.swift）。
 *
 * 字級檔位（iOS SoT，ReaderSettingsPanel.swift）：
 *   範圍 0.75…2.0，step 0.125，預設 1.0，顯示文字 `{n}x`。
 *   canDecrease = size > 0.75；canIncrease = size < 2.0。
 * 字體（iOS ReaderFont）：serif=Crimson Pro / sans=Elms Sans（phase-1 兩檔，
 *   對齊任務「serif/sans 切換」；Garamond/Mono 為 phase-2）。
 */

export const FONT_SIZE_MIN = 0.75
export const FONT_SIZE_MAX = 2.0
export const FONT_SIZE_STEP = 0.125
export const FONT_SIZE_DEFAULT = 1.0

export type LiveFont = 'serif' | 'sans'

/** epub.js registerCss 用的 font-family 串（與 web @font-face / iOS tier 同源）。 */
export const FONT_FAMILY: Record<LiveFont, string> = {
  // CrimsonPro = iOS .crimsonPro tier（reader 既有 serif 主字）。
  serif: "'CrimsonPro', Georgia, serif",
  // ElmsSans = iOS .sans tier。
  sans: "'ElmsSans', -apple-system, BlinkMacSystemFont, sans-serif",
}

export const FONT_LABEL: Record<LiveFont, string> = {
  serif: 'Crimson Pro',
  sans: 'Elms Sans',
}

export interface LiveReaderSettings {
  fontSize: number
  font: LiveFont
}

export const DEFAULT_SETTINGS: LiveReaderSettings = {
  fontSize: FONT_SIZE_DEFAULT,
  font: 'serif',
}

export function canDecrease(size: number): boolean {
  return size > FONT_SIZE_MIN + 1e-9
}
export function canIncrease(size: number): boolean {
  return size < FONT_SIZE_MAX - 1e-9
}

export function decreaseFontSize(size: number): number {
  return Math.max(FONT_SIZE_MIN, Math.round((size - FONT_SIZE_STEP) * 1000) / 1000)
}
export function increaseFontSize(size: number): number {
  return Math.min(FONT_SIZE_MAX, Math.round((size + FONT_SIZE_STEP) * 1000) / 1000)
}

/** 字級顯示文字（iOS `{n}x`：1.0→"1.0x"、0.75→"0.75x"、1.125→"1.125x"）。 */
export function fontSizeText(size: number): string {
  // 整數十分位（1.0/1.5）顯 1 位；含百分位（0.75/1.125）顯實際精度。
  const oneDecimal = Math.round(size * 10) / 10 === size
  return `${oneDecimal ? size.toFixed(1) : String(size)}x`
}

/** epub.js body CSS：把 settings 投影成 registerCss 字串（含 @font-face 絕對 URL）。 */
export function bodyCss(settings: LiveReaderSettings, origin: string): string {
  const family = FONT_FAMILY[settings.font]
  // 19px = spike 基準 baseline；fontSize 倍率對齊 iOS EPUBPreferences.fontSize。
  const px = (19 * settings.fontSize).toFixed(1)
  return `@font-face{font-family:'CrimsonPro';src:url('${origin}/fonts/CrimsonPro.woff2') format('woff2');font-weight:200 900;}
@font-face{font-family:'ElmsSans';src:url('${origin}/fonts/ElmsSans-Regular.woff2') format('woff2');font-weight:400;}
@font-face{font-family:'ElmsSans';src:url('${origin}/fonts/ElmsSans-Bold.woff2') format('woff2');font-weight:700;}
body{font-family:${family} !important;font-size:${px}px !important;line-height:1.6 !important;color:#37352f !important;padding:0 8px !important;}
p{text-align:left !important;}`
}
