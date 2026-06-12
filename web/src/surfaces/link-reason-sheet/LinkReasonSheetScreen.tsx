import type { ScenarioId } from '../../harness/scenarios'
import { LINK_REASON_SHEET_FIXTURES } from './fixtures'
import { ArrowUpRightIcon, EyeSlashIcon, PaperclipIcon } from './icons'
import './link-reason-sheet.css'

/**
 * LinkReasonSheet surface — iOS `LinkReasonSheet`（點 card-link chip 後浮出的
 * 底部 sheet）的 web 鏡像。
 *
 * 視圖樹：VStack(align .leading, spacing sectionGap=14)[
 *   HStack(.firstTextBaseline, s2=8)[paperclip(iconSmall)/tertiaryText · label(caption bold)/tertiaryText] ·
 *   Text(word).font(detailWord = mono 27 semibold)/primaryText ·
 *   CardSectionDivider(hPadding 0 → 全寬 0.5pt /divider) ·
 *   Text(reason).font(body = sans 15)/secondaryText .lineSpacing(paragraphLineSpacing=4) ·
 *   Spacer() ·
 *   VStack(spacing inlineGap=8)[
 *     ghost(primaryText)「查看詳情」+ arrow.up.right(iconTiny) ·
 *     onHide? ghost(destructive) eye.slash(iconTiny) +「隱藏此連結」
 *   ]
 * ].padding(cardBlockPadding=24).vocabCanvasBackground()
 *
 * ghost 按鈕 = label.foregroundStyle(tone).padding(.h14 .v10)、capsule 透明 at rest、
 * label.frame(maxWidth:.infinity)（置中）；字型走預設 system body 17。
 *
 * catalog scene layout = .fill 但 .vocabCanvasBackground() + scene .background(pageBackground)
 * → **opaque**（alpha-mean 1）。故 surface 填 page-bg、phone-frame 不透明捕捉（無 transparent flag）。
 */
export function LinkReasonSheetScreen({
  scenario,
}: {
  scenario: ScenarioId<'link-reason-sheet'>
}) {
  const fixture = LINK_REASON_SHEET_FIXTURES[scenario]
  return (
    <div className="lrs-surface">
      <div className="lrs-header">
        <PaperclipIcon className="lrs-header-icon" />
        <span className="lrs-label">{fixture.label}</span>
      </div>

      <div className="lrs-word">{fixture.word}</div>

      <div className="lrs-divider" />

      <div className="lrs-reason">{fixture.reason}</div>

      <div className="lrs-spacer" />

      <div className="lrs-footer">
        <button type="button" className="lrs-ghost lrs-ghost--primary">
          <span className="lrs-ghost-label">查看詳情</span>
          <ArrowUpRightIcon className="lrs-ghost-glyph" />
        </button>
        {fixture.withHide ? (
          <button type="button" className="lrs-ghost lrs-ghost--destructive">
            <EyeSlashIcon className="lrs-ghost-glyph" />
            <span className="lrs-ghost-label">隱藏此連結</span>
          </button>
        ) : null}
      </div>
    </div>
  )
}
