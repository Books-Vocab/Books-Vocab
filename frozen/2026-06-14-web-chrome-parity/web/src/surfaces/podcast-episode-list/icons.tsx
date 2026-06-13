import { makeGlyph, makeFilledGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs for Podcast Episode List — 24×24 grid，stroke 或 fill
 * currentColor，純裝飾。對應 PodcastEpisodeListView 用到的 SF Symbols。
 */

/** SF `lock.fill` — pro-locked row accessory + continue disc + continue trailing
 *  （iconSmall 12 / tertiaryText、iconSmall on brandHero、iconTiny / quaternaryText）。
 *  沿用 podcast-episode-row 的 lock.fill：shackle 半圓 + body。 */
export const LockFillIcon = makeFilledGlyph(
  '<path d="M8 10V8a4 4 0 0 1 8 0v2h-2V8a2 2 0 0 0-4 0v2z"/>' +
    '<rect x="5.5" y="10" width="13" height="10" rx="2.4"/>',
)

/** SF `waveform.slash` — empty 態 hero icon（symbolLarge 30 light / tertiaryText）。
 *  等化器豎條（高度起伏）+ 一道斜線。對齊 ref 的細線聲波 + slash。 */
export const WaveformSlashIcon = makeGlyph(
  '<path d="M5 11v2"/>' +
    '<path d="M8 8.5v7"/>' +
    '<path d="M11 6v12"/>' +
    '<path d="M14 9v6"/>' +
    '<path d="M17 7.5v9"/>' +
    '<path d="M20 11v2"/>' +
    '<path d="M5.2 17.5 18.8 6.5"/>',
  { strokeWidth: 1.4 },
)

/** SF `chevron.down` — sort menu trailing（caption 字級隨文字 / accent）。 */
export const ChevronDownIcon = makeGlyph('<path d="M5.5 9.5 12 16l6.5-6.5"/>')
