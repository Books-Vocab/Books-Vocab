import { makeGlyph, makeFilledGlyph } from '../../shared/glyph'

/**
 * SF-Symbols glyphs for the Podcast Continue Card — disc icon (play/lock/
 * person/icloud.slash by action) + trailing chevron/lock。24×24 grid，與
 * podcast / podcast-episode-row / settings 既有 glyph 同形狀（複製而非共享，
 * 每 surface 自持 icons.tsx 是 catalog 慣例）。glyph 純裝飾 (aria-hidden)。
 */

/** SF `play.fill` — actionable disc（play/resume/replay/preview）。三角略偏右視覺置中。 */
export const PlayFillIcon = makeFilledGlyph('<path d="M7 4.8v14.4l11.2-7.2z"/>')

/** SF `lock.fill` — upgrade disc 與所有 gated 變體的 trailing 鎖。shackle + body。 */
export const LockFillIcon = makeFilledGlyph(
  '<path d="M8 10V8a4 4 0 0 1 8 0v2h-2V8a2 2 0 0 0-4 0v2z"/>' +
    '<rect x="5.5" y="10" width="13" height="10" rx="2.4"/>',
)

/** SF `person.crop.circle` — signIn disc。 */
export const PersonCropCircleIcon = makeGlyph(
  '<circle cx="12" cy="12" r="9"/>' +
    '<circle cx="12" cy="10" r="3"/>' +
    '<path d="M6.4 18.2a6.2 6.2 0 0 1 11.2 0"/>',
)

/** SF `icloud.slash` — unavailable disc（音訊未就緒，muted）。 */
export const ICloudSlashIcon = makeGlyph(
  '<path d="M7 18a3.4 3.4 0 0 1-.5-6.76A4.4 4.4 0 0 1 15 9.4a3.4 3.4 0 0 1 2.2 6.05"/>' +
    '<path d="M4 4l16 16"/>',
  { strokeWidth: 1.6 },
)

/** SF `chevron.right` — actionable 變體的 trailing disclosure。 */
export const ChevronRightIcon = makeGlyph('<path d="M9.5 5.5 16 12l-6.5 6.5"/>')
