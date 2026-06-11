import type { SVGProps } from 'react'

/**
 * SF-Symbols-style glyphs for the Today Review surface — 同 notebook/settings 的
 * 視覺語言：24×24 grid、stroke:currentColor；實心符號另用 fill 工廠。glyph 純
 * 裝飾（aria-hidden）。
 */
function glyph(paths: string) {
  return function Glyph({ size = 24, strokeWidth = 1.7, ...rest }: SVGProps<SVGSVGElement> & { size?: number; strokeWidth?: number }) {
    return (
      <svg
        viewBox="0 0 24 24"
        width={size}
        height={size}
        fill="none"
        stroke="currentColor"
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        focusable="false"
        dangerouslySetInnerHTML={{ __html: paths }}
        {...rest}
      />
    )
  }
}

function filledGlyph(paths: string) {
  return function FilledGlyph({ size = 24, ...rest }: SVGProps<SVGSVGElement> & { size?: number }) {
    return (
      <svg
        viewBox="0 0 24 24"
        width={size}
        height={size}
        fill="currentColor"
        stroke="none"
        aria-hidden="true"
        focusable="false"
        dangerouslySetInnerHTML={{ __html: paths }}
        {...rest}
      />
    )
  }
}

/** SF `shuffle` — 洗牌 pill。 */
export const ShuffleIcon = glyph(
  '<path d="M3 7h3.2c1.2 0 2.3.6 3 1.6l4.6 6.8c.7 1 1.8 1.6 3 1.6H21"/>' +
    '<path d="M3 17h3.2c1.2 0 2.3-.6 3-1.6l4.6-6.8c.7-1 1.8-1.6 3-1.6H21"/>' +
    '<path d="M18 4l3 3-3 3"/><path d="M18 14l3 3-3 3"/>',
)

/** SF `play.circle` — autoplay 開關（off 狀態，描邊圓 + 實心三角）。 */
export const PlayCircleIcon = glyph(
  '<circle cx="12" cy="12" r="9"/>' +
    '<path d="M10 8.5l5 3.5-5 3.5z" fill="currentColor" stroke="none"/>',
)

/** SF `xmark` — 關閉。 */
export const XmarkIcon = glyph('<path d="M6 6l12 12M18 6L6 18"/>')

/** SF `speaker.wave.2.fill` — 播放發音 chrome。 */
export const SpeakerWaveIcon = filledGlyph(
  '<path d="M4 9.5h2.8L11 6v12l-4.2-3.5H4z"/>' +
    '<path d="M14.2 9a4 4 0 0 1 0 6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>' +
    '<path d="M16.6 6.8a7 7 0 0 1 0 10.4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
)

/** SF `arrow.up.right` — 查看詳情 chrome。 */
export const ArrowUpRightIcon = glyph('<path d="M7 17L17 7"/><path d="M8 7h9v9"/>')

/** SF `chevron.up` — 摺頁收合手柄（semibold）。 */
export const ChevronUpIcon = glyph('<path d="M5 15l7-7 7 7"/>')

/** SF `paperclip` — link strip 前綴。 */
export const PaperclipIcon = glyph(
  '<path d="M17 8.5l-7.4 7.4a2.5 2.5 0 0 1-3.5-3.5l7.8-7.8a3.7 3.7 0 0 1 5.2 5.2l-7.6 7.6a4.9 4.9 0 0 1-7-7l7-7"/>',
)

/** SF `plus`（細）— link strip 新增連結。 */
export const PlusThinIcon = glyph('<path d="M12 6v12M6 12h12"/>')

/** SF `xmark`（粗短）— 忘記按鈕內 icon。 */
export const XmarkBoldIcon = glyph('<path d="M6 6l12 12M18 6L6 18"/>')

/** SF `checkmark` — 記得按鈕內 icon。 */
export const CheckmarkIcon = glyph('<path d="M5 12.5l5 5 9-11"/>')

/** SF `chevron.left` — nav 上一張。 */
export const ChevronLeftIcon = glyph('<path d="M15 5l-7 7 7 7"/>')

/** SF `chevron.right` — nav 下一張。 */
export const ChevronRightIcon = glyph('<path d="M9 5l7 7-7 7"/>')
