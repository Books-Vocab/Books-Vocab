import { makeGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs for Settings Sections · Review（複習節奏）— 24×24
 * grid、stroke:currentColor、純裝飾（aria-hidden）。對齊 SettingsReviewSection.swift
 * 的 SF symbol：section header（pause.circle / timer / slider.horizontal.3）、
 * 模式 tile（heart / bolt / gearshape）、stepper（minus / plus）。
 */

/** SF `pause.circle` — 暫停進度 section header。 */
export const PauseCircleIcon = makeGlyph(
  '<circle cx="12" cy="12" r="9"/>' +
    '<path d="M10 9v6M14 9v6"/>',
)

/** SF `timer` — 複習模式 section header（與 settings/icons TimerIcon 同形）。 */
export const TimerIcon = makeGlyph(
  '<circle cx="12" cy="13" r="7.6"/>' +
    '<path d="M12 13l3.2-3.2M10 3.4h4"/>',
)

/** SF `slider.horizontal.3` — 自訂參數 section header（與 settings/icons SlidersIcon 同形）。 */
export const SlidersIcon = makeGlyph(
  '<path d="M4 7h7M15 7h5M4 12h2.5M10.5 12H20M4 17h9M17 17h3"/>' +
    '<circle cx="13" cy="7" r="1.9"/><circle cx="8.5" cy="12" r="1.9"/><circle cx="15" cy="17" r="1.9"/>',
)

/** SF `heart` — 寬鬆模式 tile 圖示。 */
export const HeartIcon = makeGlyph(
  '<path d="M12 20.3c-.5 0-1-.2-1.4-.5C7 16.9 4 14.2 4 10.6 4 8 6 6 8.5 6c1.4 0 2.7.7 3.5 1.8C12.8 6.7 14.1 6 15.5 6 18 6 20 8 20 10.6c0 3.6-3 6.3-6.6 9.2-.4.3-.9.5-1.4.5z"/>',
)

/** SF `bolt` — 密集模式 tile 圖示。 */
export const BoltIcon = makeGlyph(
  '<path d="M13 3 5.5 13.4h5.3L11 21l7.5-10.4h-5.3z"/>',
)

/** SF `gearshape` — 自訂模式 tile 圖示。 */
export const GearShapeIcon = makeGlyph(
  '<path d="M19.3 13.3a7.4 7.4 0 0 0 0-2.6l1.7-1.3-1.7-3-2 .8a7.4 7.4 0 0 0-2.3-1.3L14.6 3.8H10.4l-.4 2.1a7.4 7.4 0 0 0-2.3 1.3l-2-.8-1.7 3 1.7 1.3a7.4 7.4 0 0 0 0 2.6l-1.7 1.3 1.7 3 2-.8a7.4 7.4 0 0 0 2.3 1.3l.4 2.1h4.2l.4-2.1a7.4 7.4 0 0 0 2.3-1.3l2 .8 1.7-3z"/>' +
    '<circle cx="12" cy="12" r="2.6"/>',
)

/** SF `minus` — stepper 減量按鈕。 */
export const MinusIcon = makeGlyph('<path d="M5.5 12h13"/>', { strokeWidth: 2 })

/** SF `plus` — stepper 增量按鈕。 */
export const PlusIcon = makeGlyph('<path d="M12 5.5v13M5.5 12h13"/>', { strokeWidth: 2 })
