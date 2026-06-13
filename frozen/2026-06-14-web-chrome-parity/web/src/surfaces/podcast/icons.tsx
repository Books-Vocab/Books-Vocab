import type { SVGProps } from 'react'
import { makeGlyph, makeFilledGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs for the Podcast player surface — 同 notebook/settings
 * 的視覺語言：24×24 grid、stroke 或 fill currentColor。glyph 純裝飾
 * (aria-hidden)，語意掛在外層元素。
 */

/** SF `play.fill` — 主 play CTA（brandHero disc）。三角形略偏右視覺置中。 */
export const PlayFillIcon = makeFilledGlyph('<path d="M7 4.8v14.4l11.2-7.2z"/>')

/** SF `pause.fill` — 播放中時 play disc 切換為暫停。雙豎條。 */
export const PauseFillIcon = makeFilledGlyph(
  '<rect x="6.5" y="5" width="3.6" height="14" rx="1"/>' +
    '<rect x="13.9" y="5" width="3.6" height="14" rx="1"/>',
)

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

/** SF `moon.zzz` — sleep timer control。crescent + 小 z。 */
export const MoonIcon = makeGlyph(
  '<path d="M19 14.5A7.5 7.5 0 0 1 9.5 5a6 6 0 1 0 9.5 9.5z"/>' +
    '<path d="M16 4h3l-3 3.4h3" stroke-width="1.2"/>',
)

/** SF `captions.bubble` — subtitle size/follow control。氣泡 + cc 線。 */
export const CaptionsIcon = makeGlyph(
  '<rect x="3.5" y="4.5" width="17" height="12" rx="3"/>' +
    '<path d="M9 8.5H8a2 2 0 0 0 0 4h1M16 8.5h-1a2 2 0 0 0 0 4h1"/>' +
    '<path d="M8.5 19.5 12 16.5l3.5 3z" fill="currentColor" stroke="none"/>',
)

/** SF `list.bullet` — continuous-playback / queue control。 */
export const ListBulletIcon = makeGlyph(
  '<path d="M8 6.5h11M8 12h11M8 17.5h11"/>' +
    '<circle cx="4.5" cy="6.5" r="1.1" fill="currentColor" stroke="none"/>' +
    '<circle cx="4.5" cy="12" r="1.1" fill="currentColor" stroke="none"/>' +
    '<circle cx="4.5" cy="17.5" r="1.1" fill="currentColor" stroke="none"/>',
)

/** SF `ellipsis` — overflow options (opens the option sheet)。 */
export const EllipsisIcon = makeGlyph(
  '<circle cx="5" cy="12" r="1.4" fill="currentColor" stroke="none"/>' +
    '<circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none"/>' +
    '<circle cx="19" cy="12" r="1.4" fill="currentColor" stroke="none"/>',
)

/** SF `forward.end.fill` — skip to next episode (continuous)。 */
export const ForwardEndFillIcon = makeFilledGlyph(
  '<path d="M5 5.5v13l9-6.5z"/>' + '<rect x="15" y="5" width="3" height="14" rx="1"/>',
)

/** SF `checkmark` — selected option in the sheet。 */
export const CheckmarkIcon = makeGlyph('<path d="M5 12.5l4.5 4.5L19 6"/>', { strokeWidth: 2 })
