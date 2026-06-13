import { makeFilledGlyph, makeGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs for the Podcast · Episode Row surface — 24×24 grid，
 * stroke 或 fill currentColor，純裝飾。對應 PodcastEpisodeRow.swift 的 SF Symbols。
 */

/** SF `play.circle.fill` — trailing 主 play 配件（iconSmall 12pt medium / accent）。 */
export const PlayCircleFillIcon = makeFilledGlyph(
  '<circle cx="12" cy="12" r="10"/>' +
    '<path d="M9.6 8.2v7.6l6-3.8z" fill="var(--page-bg)"/>',
)

/** SF `checkmark.circle.fill` — 已聽完（iconSmall / success）。 */
export const CheckmarkCircleFillIcon = makeFilledGlyph(
  '<circle cx="12" cy="12" r="10"/>' +
    '<path d="M7.6 12.2l2.8 2.8 5.6-6" fill="none" stroke="var(--page-bg)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
)

/** SF `lock.fill` — pro-locked（iconSmall / tertiaryText）。shackle 半圓 + body。 */
export const LockFillIcon = makeFilledGlyph(
  '<path d="M8 10V8a4 4 0 0 1 8 0v2h-2V8a2 2 0 0 0-4 0v2z"/>' +
    '<rect x="5.5" y="10" width="13" height="10" rx="2.4"/>',
)

/** SF `icloud.slash` — audio unavailable（iconSmall stroke / quaternaryText）。 */
export const ICloudSlashIcon = makeGlyph(
  '<path d="M7 18a3.4 3.4 0 0 1-.5-6.76A4.4 4.4 0 0 1 15 9.4a3.4 3.4 0 0 1 2.2 6.05"/>' +
    '<path d="M4 4l16 16"/>',
  { strokeWidth: 1.6 },
)

/** SF `captions.bubble.fill` — subtitle available（iconTiny 10pt thin / success）。 */
export const CaptionsBubbleFillIcon = makeFilledGlyph(
  '<path d="M5 4h14a2.4 2.4 0 0 1 2.4 2.4v8.2A2.4 2.4 0 0 1 19 17h-7.4L7 20.6V17H5a2.4 2.4 0 0 1-2.4-2.4V6.4A2.4 2.4 0 0 1 5 4z"/>' +
    '<rect x="6" y="8.4" width="5.2" height="1.8" rx="0.9" fill="var(--page-bg)"/>' +
    '<rect x="12.4" y="8.4" width="5.6" height="1.8" rx="0.9" fill="var(--page-bg)"/>' +
    '<rect x="6" y="11.6" width="7.2" height="1.8" rx="0.9" fill="var(--page-bg)"/>' +
    '<rect x="14.4" y="11.6" width="3.6" height="1.8" rx="0.9" fill="var(--page-bg)"/>',
)
