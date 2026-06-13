import type { SVGProps } from 'react'
import { makeGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs for NotebookEditSheet — 24×24 grid。
 * - checkmark：色圈選定標記（caption font / .white），stroke-only。
 * - checkmark.circle.fill：pattern tile 選定標記（iconSmall / .white），白圓盤 + 勾鏤空。
 * - photo：自訂圖片「選擇圖片」Label 前綴（系統 body / tint）。
 */

/** SF `checkmark` — 色圈 selected（白勾）。 */
export const CheckmarkIcon = makeGlyph('<path d="M5 12.5 10 17.5 19 6.5"/>', {
  size: 15,
  strokeWidth: 2,
})

/**
 * SF `checkmark.circle.fill`（foregroundStyle(.white)）— 白圓盤、勾為**鏤空**透出底下
 * tile（色 + pattern）。以 SVG mask 實作：白 disc 扣掉勾形 → 色彩無關的忠實 knockout。
 * 每 scene 至多一個 selected tile → 靜態 mask id 安全。
 */
export function CheckmarkCircleFillIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={18}
      height={18}
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      <mask id="nbe-check-knockout">
        <rect width="24" height="24" fill="black" />
        <circle cx="12" cy="12" r="10" fill="white" />
        <path
          d="M7.2 12.2 10.6 15.6 16.8 8.4"
          fill="none"
          stroke="black"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </mask>
      <rect width="24" height="24" fill="#fff" mask="url(#nbe-check-knockout)" />
    </svg>
  )
}

/** SF `photo` — 選擇圖片前綴（相片框 + 山形 + 太陽）。 */
export const PhotoIcon = makeGlyph(
  '<rect x="3" y="5" width="18" height="14" rx="2.5"/>' +
    '<circle cx="8.5" cy="10" r="1.4"/>' +
    '<path d="M5 17.5 10 12.5l3 3 3.5-3.5 2.5 2.5"/>',
  { size: 19, strokeWidth: 1.6 },
)
