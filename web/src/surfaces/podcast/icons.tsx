import type { SVGProps } from 'react'
import { makeGlyph, makeFilledGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs for the Podcast player surface — 同 notebook/settings
 * 的視覺語言：24×24 grid、stroke 或 fill currentColor。glyph 純裝飾
 * (aria-hidden)，語意掛在外層元素。
 */

/** SF `play.fill` — 主 play CTA（brandHero disc）。三角形略偏右視覺置中。 */
export const PlayFillIcon = makeFilledGlyph('<path d="M7 4.8v14.4l11.2-7.2z"/>')

/**
 * SF `gobackward.15` / `goforward.15` — 15s skip ghost 按鈕。圓弧 + 箭頭 + 內嵌
 * 「15」。`mirror` 翻轉成 forward。`15` 以小字 path 近似 SF 的內嵌數字。
 * skip15 為複合圖示（混合 JSX 結構），不走 makeGlyph 工廠。
 */
function skip15(mirror: boolean) {
  return function Skip15({ size = 24, strokeWidth = 1.6, ...rest }: SVGProps<SVGSVGElement> & { size?: number; strokeWidth?: number }) {
    return (
      <svg
        viewBox="0 0 24 24"
        width={size}
        height={size}
        aria-hidden="true"
        focusable="false"
        {...rest}
      >
        <g transform={mirror ? 'translate(24,0) scale(-1,1)' : undefined}>
          {/* 開口在頂端的圓弧（gobackward）：從 ~12 點鐘逆時針繞回，留缺口給箭頭 */}
          <path
            d="M12 5.2 A6.8 6.8 0 1 0 18.4 9.8"
            fill="none"
            stroke="currentColor"
            strokeWidth={strokeWidth}
            strokeLinecap="round"
          />
          {/* 缺口處的回轉箭頭 */}
          <path
            d="M12 2.4 L12 8 L7.2 5.2 Z"
            fill="currentColor"
            stroke="none"
          />
        </g>
        {/* 內嵌「15」— 不翻轉，恆正立 */}
        <text
          x="12"
          y="15.6"
          textAnchor="middle"
          fontSize="7.2"
          fontWeight="700"
          fontFamily="var(--font-sans)"
          fill="currentColor"
          stroke="none"
        >
          15
        </text>
      </svg>
    )
  }
}

export const GoBackward15Icon = skip15(false)
export const GoForward15Icon = skip15(true)

/** SF `lock.fill` — 鎖定 gate hero。shackle 半圓 + body 圓角矩形。 */
export const LockFillIcon = makeFilledGlyph(
  '<path d="M8 10V8a4 4 0 0 1 8 0v2h-2V8a2 2 0 0 0-4 0v2z"/>' +
    '<rect x="5.5" y="10" width="13" height="10" rx="2.4"/>',
)

/** SF `lock.circle.fill` — preview banner 前綴鎖 disc。 */
export const LockCircleFillIcon = makeFilledGlyph(
  '<circle cx="12" cy="12" r="10"/>' +
    '<path d="M9.2 11V9.6a2.8 2.8 0 0 1 5.6 0V11h.6a.9.9 0 0 1 .9.9v3.6a.9.9 0 0 1-.9.9H8.6a.9.9 0 0 1-.9-.9v-3.6a.9.9 0 0 1 .9-.9zm1.4 0h2.8V9.6a1.4 1.4 0 0 0-2.8 0z" fill="var(--brand-hero)"/>',
)

/** SF `person.crop.circle` — sign-in 按鈕 leading glyph。 */
export const PersonCropCircleIcon = makeGlyph(
  '<circle cx="12" cy="12" r="9"/>' +
    '<circle cx="12" cy="10" r="3"/>' +
    '<path d="M6.4 18.2a6.2 6.2 0 0 1 11.2 0"/>',
)
