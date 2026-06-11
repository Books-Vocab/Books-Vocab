import type { SVGProps } from 'react'

/**
 * SF-Symbols-style glyphs for the Reader chrome — 同 notebook/settings 的視覺
 * 語言：24×24 grid、stroke:currentColor。glyph 純裝飾（aria-hidden），語意掛在
 * 外層按鈕。chrome 用的 SF symbol：book.closed / ellipsis / chevron.left /
 * list.bullet / textformat.size / text.book.closed / chevron.up /
 * exclamationmark.triangle。
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

/** SF `book.closed` — compact 進度膠囊前綴 + expanded text.book.closed 鈕共用書本形。 */
export const BookClosedIcon = glyph(
  '<rect x="5.5" y="4" width="13" height="16" rx="1.5"/>' +
    '<path d="M5.5 17.2h13"/>',
)

/** SF `ellipsis` — compact header 展開鈕（三點橫排）。 */
export const EllipsisIcon = glyph(
  '<circle cx="6" cy="12" r="0.9" fill="currentColor" stroke="none"/>' +
    '<circle cx="12" cy="12" r="0.9" fill="currentColor" stroke="none"/>' +
    '<circle cx="18" cy="12" r="0.9" fill="currentColor" stroke="none"/>',
)

/** SF `chevron.left` — expanded header 返回（書庫）。 */
export const ChevronLeftIcon = glyph('<path d="M14.5 5.5 8 12l6.5 6.5"/>')

/** SF `chevron.up` — expanded header 收起標題列。 */
export const ChevronUpIcon = glyph('<path d="M5.5 14.5 12 8l6.5 6.5"/>')

/** SF `list.bullet` — expanded header 目錄。 */
export const ListBulletIcon = glyph(
  '<path d="M9 6.5h10M9 12h10M9 17.5h10"/>' +
    '<circle cx="5" cy="6.5" r="0.9" fill="currentColor" stroke="none"/>' +
    '<circle cx="5" cy="12" r="0.9" fill="currentColor" stroke="none"/>' +
    '<circle cx="5" cy="17.5" r="0.9" fill="currentColor" stroke="none"/>',
)

/** SF `textformat.size` — expanded header 閱讀設定（大小：大 A + 小 A）。 */
export const TextformatSizeIcon = glyph(
  '<path d="M3 17.5 6.5 7l3.5 10.5M3.9 14.5h5.2"/>' +
    '<path d="M14 17.5 16.6 10l2.6 7.5M14.6 15.3h4"/>',
)

/** SF `exclamationmark.triangle` — error 卡圖示。 */
export const WarningTriangleIcon = glyph(
  '<path d="M12 4 21 19.5H3z"/>' +
    '<path d="M12 9.5v4.5"/>' +
    '<circle cx="12" cy="16.8" r="0.95" fill="currentColor" stroke="none"/>',
)

/* ============================================================
   Translation panel glyphs（R2）— TranslationVocabPresenter 的 SF symbol：
   speaker.wave.2 / text.bubble / chevron.down / chevron.up / trash / xmark /
   checkmark.circle.fill / exclamationmark.triangle.fill / translate。
   ============================================================ */

/** SF `speaker.wave.2` — hero 朗讀鈕（喇叭 + 兩道音波）。iconTiny thin。 */
export const SpeakerWaveIcon = glyph(
  '<path d="M4 9.5h3l4-3.2v11.4l-4-3.2H4z"/>' +
    '<path d="M14.4 9.2a3.6 3.6 0 0 1 0 5.6"/>' +
    '<path d="M16.6 7.2a6.4 6.4 0 0 1 0 9.6"/>',
)

/** SF `text.bubble` — 「語境解釋」label 前綴（對話泡 + 三行文字）。 */
export const TextBubbleIcon = glyph(
  '<path d="M4 5.5h16v10H10l-4 3.2V15.5H4z"/>' +
    '<path d="M7.5 9h9M7.5 12h6"/>',
)

/** SF `chevron.down` — collapsed/large 切換（展開↓）。 */
export const ChevronDownIcon = glyph('<path d="M5.5 9.5 12 16l6.5-6.5"/>')

/** SF `trash` — 刪除單字（destructive tone）。 */
export const TrashIcon = glyph(
  '<path d="M5 6.5h14"/>' +
    '<path d="M9 6.5V4.8h6v1.7"/>' +
    '<path d="M6.5 6.5 7.4 19.2h9.2L17.5 6.5"/>' +
    '<path d="M10 10v6M14 10v6"/>',
)

/** SF `xmark` — 關閉面板。 */
export const XmarkIcon = glyph('<path d="M6 6 18 18M18 6 6 18"/>')

/** SF `checkmark.circle.fill` — footer「已加入」前綴（success tone，實心圓 + 勾）。 */
export const CheckmarkCircleFillIcon = glyph(
  '<circle cx="12" cy="12" r="9" fill="currentColor" stroke="none"/>' +
    '<path d="M8 12.2 11 15.2 16.2 9.4" stroke="#fff" stroke-width="2"/>',
)

/** SF `exclamationmark.triangle.fill` — state message card error 圖示（accent fill 三角 + 白驚嘆號）。 */
export const WarningTriangleFillIcon = glyph(
  '<path d="M12 4 21 19.5H3z" fill="currentColor" stroke="none"/>' +
    '<path d="M12 9.5v4.5" stroke="#fff" stroke-width="2"/>' +
    '<circle cx="12" cy="16.8" r="1.05" fill="#fff" stroke="none"/>',
)

/** SF `translate` — loading state card 圖示（A→譯，雙語泡）。accent fill。 */
export const TranslateIcon = glyph(
  '<rect x="3.2" y="4.2" width="10" height="8" rx="1.6" fill="currentColor" stroke="none"/>' +
    '<rect x="10.8" y="10.4" width="10" height="8" rx="1.6" fill="currentColor" stroke="none"/>' +
    '<path d="M5.4 9.8 7 6.4l1.6 3.4M5.8 8.7h2.4" stroke="#fff" stroke-width="1.3"/>' +
    '<path d="M13.4 13.6h5M15.9 13v.6M16.9 14.2a4.5 4.5 0 0 1-3.5 3M14.8 14.8a4.5 4.5 0 0 0 3.6 2.8" stroke="#fff" stroke-width="1.2"/>',
)

/* ============================================================
   Reader 面板群 glyphs（R3）— TOC / Settings / Notebook Picker 專屬 SF symbol。
   注意：WarningTriangleFillIcon / XmarkIcon / ChevronDownIcon 已由 R2 區段定義，
   R3 共用同一份（整合 branch 已驗證），此處不重複宣告。
   ============================================================ */

/** SF `text.book.closed` — TOC loading 卡圖示（書 + 文字線）。 */
export const TextBookClosedIcon = glyph(
  '<rect x="4.5" y="3.5" width="13" height="17" rx="1.6" fill="currentColor" stroke="none" opacity="0.16"/>' +
    '<rect x="4.5" y="3.5" width="13" height="17" rx="1.6"/>' +
    '<path d="M4.5 17.4h13"/>' +
    '<path d="M7.4 7.5h7M7.4 10.6h7M7.4 13.7h4.5" stroke-width="1.3"/>',
)

/** SF `list.bullet.rectangle` — TOC empty 卡圖示（外框 + 條目）。 */
export const ListBulletRectIcon = glyph(
  '<rect x="3.5" y="5" width="17" height="14" rx="2.2"/>' +
    '<path d="M9 9h7.5M9 12h7.5M9 15h7.5" stroke-width="1.4"/>' +
    '<circle cx="6.3" cy="9" r="0.85" fill="currentColor" stroke="none"/>' +
    '<circle cx="6.3" cy="12" r="0.85" fill="currentColor" stroke="none"/>' +
    '<circle cx="6.3" cy="15" r="0.85" fill="currentColor" stroke="none"/>',
)

/** SF `checkmark` — Notebook 選中 / 列表勾。 */
export const CheckmarkIcon = glyph('<path d="M4.5 12.5 9.5 18 19.5 6.5"/>')

/** SF `text.line.spacing` — 行距 chip。 */
export const LineSpacingIcon = glyph(
  '<path d="M3 6h13M3 12h13M3 18h13" stroke-width="1.4"/>' +
    '<path d="M20 5.5v13M17.5 8 20 5.5 22.5 8M17.5 16 20 18.5 22.5 16" stroke-width="1.4"/>',
)

/** SF `book.pages` — 閱讀模式 chip。 */
export const BookPagesIcon = glyph(
  '<path d="M5 5.5h7.5a2 2 0 0 1 2 2V20H7a2 2 0 0 1-2-2z"/>' +
    '<path d="M14.5 7.5a2 2 0 0 1 2-2H19v12.5h-2.5a2 2 0 0 0-2 2"/>',
)

/** SF `sun.max` — Light theme tile。 */
export const SunIcon = glyph(
  '<circle cx="12" cy="12" r="4"/>' +
    '<path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.2 5.2l1.6 1.6M17.2 17.2l1.6 1.6M18.8 5.2l-1.6 1.6M6.8 17.2l-1.6 1.6" stroke-width="1.4"/>',
)

/** SF `book` (open) — Sepia theme tile。 */
export const BookOpenIcon = glyph(
  '<path d="M12 6.5C10 5 7 4.5 4.5 5v13C7 17.5 10 18 12 19.5 14 18 17 17.5 19.5 18V5C17 4.5 14 5 12 6.5z" fill="currentColor" stroke="none"/>' +
    '<path d="M12 6.5v13" stroke="#ffffff" stroke-width="0.9"/>',
)

/** SF `moon.stars` — Dark theme tile。 */
export const MoonStarsIcon = glyph(
  '<path d="M19 14.5A7.2 7.2 0 0 1 9.5 5a5.2 5.2 0 0 0-1 .3 7.5 7.5 0 1 0 9.6 10 5.4 5.4 0 0 0 .9-.8z"/>' +
    '<path d="M17.5 4l.5 1.4 1.4.5-1.4.5-.5 1.4-.5-1.4L15.6 6l1.4-.5z" fill="currentColor" stroke="none"/>',
)

/** SF `globe` — Notebook「跟隨全域設定」前綴。 */
export const GlobeIcon = glyph(
  '<circle cx="12" cy="12" r="8.2"/>' +
    '<path d="M3.8 12h16.4M12 3.8c2.4 2.2 3.7 5.2 3.7 8.2S14.4 18 12 20.2C9.6 18 8.3 15 8.3 12S9.6 6 12 3.8zM5 7.2c2 1.1 4.4 1.7 7 1.7s5-0.6 7-1.7M5 16.8c2-1.1 4.4-1.7 7-1.7s5 .6 7 1.7" stroke-width="1.2"/>',
)
