import type { SVGProps } from 'react'
import { makeGlyph, makeFilledGlyph } from '../../shared/glyph'

/**
 * SyncPresenter 用到的 SF Symbol glyph。形狀逐一對應 iOS `Image(systemName:)`：
 * 路徑沿用其他 surface 的同源 glyph（self-contained 複製），尺寸/色由 caller 控。
 */

/** SF `arrow.triangle.2.circlepath` — ready/running hero 雙箭頭循環。 */
export const SyncIcon = makeGlyph(
  '<path d="M5.2 10a7 7 0 0 1 12-2.5l1.6 1.8M18.8 14a7 7 0 0 1-12 2.5l-1.6-1.8"/>' +
    '<path d="M18.9 5.2v4.1h-4.1M5.1 18.8v-4.1h4.1"/>',
)

/** SF `checkmark.circle.fill` — completed hero / step done / summary（白勾於填色圓）。 */
export const CheckmarkCircleFillIcon = makeGlyph(
  '<circle cx="12" cy="12" r="9" fill="currentColor" stroke="none"/>' +
    '<path d="M8 12.2 11 15.2 16.2 9.4" stroke="#fff" stroke-width="2"/>',
)

/** SF `exclamationmark.triangle.fill` — full-failure hero / summary（填色三角驚嘆）。 */
export const WarningTriangleFillIcon = makeGlyph(
  '<path d="M12 4 21 19.5H3z" fill="currentColor" stroke="none"/>' +
    '<path d="M12 9.5v4.5" stroke="#fff" stroke-width="2"/>' +
    '<circle cx="12" cy="16.8" r="1.05" fill="#fff" stroke="none"/>',
)

/** SF `xmark.circle.fill` — step error（填色圓內白叉）。 */
export const XmarkCircleFillIcon = makeFilledGlyph(
  '<path fill-rule="evenodd" clip-rule="evenodd" d="M12 2a10 10 0 100 20 10 10 0 000-20zM8.4 7.1a.9.9 0 00-1.3 1.3L10.7 12l-3.6 3.6a.9.9 0 101.3 1.3L12 13.3l3.6 3.6a.9.9 0 101.3-1.3L13.3 12l3.6-3.6a.9.9 0 10-1.3-1.3L12 10.7 8.4 7.1z"/>',
)

/** SF `arrow.clockwise` — 重試按鈕 label。 */
export const RefreshIcon = makeGlyph(
  '<path d="M20 12a8 8 0 1 1-2.3-5.6"/><path d="M20 4v4h-4"/>',
)

/** SF `circle` — step waiting（空心圓）。 */
export const CircleIcon = makeGlyph('<circle cx="12" cy="12" r="8.5"/>')

/** SF `minus.circle` — 移除待收錄 accessory（空心圓內減號）。 */
export const MinusCircleIcon = makeGlyph(
  '<circle cx="12" cy="12" r="8.5"/><path d="M8 12h8"/>',
)

/** SF `arrow.uturn.backward` — 復原刪除 accessory。 */
export const UturnBackwardIcon = makeGlyph(
  '<path d="M9 7 5 11l4 4"/><path d="M5 11h9a4.5 4.5 0 0 1 0 9h-3.5"/>',
)

/**
 * SF `exclamationmark.arrow.trianglehead.2.clockwise.rotate.90` —
 * partial-failure hero / summary。雙弧循環箭頭 + 中央驚嘆號。
 */
export const ExclamationCirclePathIcon = makeGlyph(
  '<path d="M18.2 8.1a7 7 0 0 0-12.2 1.4"/>' +
    '<path d="M5.8 15.9a7 7 0 0 0 12.2-1.4"/>' +
    '<path d="M6.4 5.4v4.1h4.1M17.6 18.6v-4.1h-4.1"/>' +
    '<path d="M12 8.4v4" stroke-linecap="round"/>' +
    '<circle cx="12" cy="14.8" r="0.95" fill="currentColor" stroke="none"/>',
)

/**
 * UIActivityIndicator（ProgressView 圓形）— 12 條輻射灰條的靜態相位。
 * iOS catalog 截圖為某一旋轉相位，此處取均勻灰階的固定快照。
 */
export function ActivityIndicator({
  size = 20,
  ...rest
}: SVGProps<SVGSVGElement> & { size?: number }) {
  const bars = Array.from({ length: 12 }, (_, i) => {
    const angle = (i * 360) / 12
    // 由淺到深的相位漸層，模擬旋轉殘影
    const opacity = 0.25 + (i / 12) * 0.6
    return (
      <rect
        key={i}
        x="11.1"
        y="2"
        width="1.8"
        height="5"
        rx="0.9"
        fill="currentColor"
        opacity={opacity}
        transform={`rotate(${angle} 12 12)`}
      />
    )
  })
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {bars}
    </svg>
  )
}
