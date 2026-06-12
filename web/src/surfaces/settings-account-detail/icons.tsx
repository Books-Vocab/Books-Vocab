import { makeGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs for Settings Account Detail — 24×24 grid、純裝飾
 * （aria-hidden）。形狀沿用各既有 surface 已建立的鏡像（settings/account-section/
 * reader），與 SettingsAccountDetailView.swift 用到的 SF symbol 對應。
 */

/** SF `person.crop.circle` — 「帳號資訊」section header（stroke）。沿用 account-section。 */
export const PersonCircleIcon = makeGlyph(
  '<circle cx="12" cy="12" r="9"/>' +
    '<circle cx="12" cy="9.6" r="3.1"/>' +
    '<path d="M5.8 18.6c1.2-2.6 3.5-4 6.2-4s5 1.4 6.2 4"/>',
)

/** SF `person` — 名稱列 leading（iconSmall 12 / secondaryText）。 */
export const PersonIcon = makeGlyph(
  '<circle cx="12" cy="8" r="3.4"/>' +
    '<path d="M5.5 19c0-3.4 2.9-5.4 6.5-5.4s6.5 2 6.5 5.4"/>',
)

/** SF `envelope` — 信箱列 leading（iconSmall 12 / secondaryText）。 */
export const EnvelopeIcon = makeGlyph(
  '<rect x="3.5" y="6" width="17" height="12" rx="2.2"/>' +
    '<path d="M4 7.5 12 13l8-5.5"/>',
)

/** SF `tray.and.arrow.up` — 「資料管理」section header。 */
export const TrayArrowUpIcon = makeGlyph(
  '<path d="M12 3.5v8"/>' +
    '<path d="M8.6 6.6 12 3.2l3.4 3.4"/>' +
    '<path d="M4 13.5h3.5l1.4 2h6.2l1.4-2H20v4.5a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18z"/>',
)

/** SF `square.and.arrow.up` — 「匯出全部單字 CSV」列 leading（iconSmall 12 / secondaryText）。 */
export const SquareArrowUpIcon = makeGlyph(
  '<path d="M12 3.5v10"/>' +
    '<path d="M8.6 6.6 12 3.2l3.4 3.4"/>' +
    '<path d="M6 10.5H4.5v8a1.5 1.5 0 0 0 1.5 1.5h12a1.5 1.5 0 0 0 1.5-1.5v-8H18"/>',
)

/** SF `chevron.right` — navigation row trailing（iconTiny 10 thin / tertiaryText）。 */
export const ChevronRightIcon = makeGlyph('<path d="M9.5 5.5 16 12l-6.5 6.5"/>')

/** SF `exclamationmark.triangle` — 「危險操作」section header（stroke / secondaryText）。 */
export const WarningTriangleIcon = makeGlyph(
  '<path d="M12 4 21 19.5H3z"/>' +
    '<path d="M12 9.5v4.5"/>' +
    '<circle cx="12" cy="16.8" r="0.95" fill="currentColor" stroke="none"/>',
)

/** SF `exclamationmark.triangle.fill` — 危險操作狀態卡（iconSmall 12，accent fill 三角 + 白驚嘆）。 */
export const WarningTriangleFillIcon = makeGlyph(
  '<path d="M12 4 21 19.5H3z" fill="currentColor" stroke="none"/>' +
    '<path d="M12 9.5v4.5" stroke="var(--card-bg, #fff)" stroke-width="2"/>' +
    '<circle cx="12" cy="16.8" r="1.05" fill="var(--card-bg, #fff)" stroke="none"/>',
)

/** SF `hourglass` — 刪除中狀態卡（iconSmall 12，accent）。沙漏外框 + 上下沙堆。 */
export const HourglassIcon = makeGlyph(
  '<path d="M7 4h10M7 20h10"/>' +
    '<path d="M7.5 4c0 4 4.5 5.5 4.5 8s-4.5 4-4.5 8"/>' +
    '<path d="M16.5 4c0 4-4.5 5.5-4.5 8s4.5 4 4.5 8"/>' +
    '<path d="M9 6.4h6M9.6 17.6h4.8" stroke-width="2"/>',
)

/** SF `trash` — 刪除帳號鈕 trailing（iconTiny 10 / destructive）。沿用 reader trash。 */
export const TrashIcon = makeGlyph(
  '<path d="M5 6.5h14"/>' +
    '<path d="M9 6.5V4.8h6v1.7"/>' +
    '<path d="M6.5 6.5 7.4 19.2h9.2L17.5 6.5"/>' +
    '<path d="M10 10v6M14 10v6"/>',
)
