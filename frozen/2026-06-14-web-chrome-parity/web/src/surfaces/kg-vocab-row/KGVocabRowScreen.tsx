import type { ScenarioId } from '../../harness/scenarios'
import { KG_VOCAB_ROW_FIXTURES } from './fixtures'
import './kg-vocab-row.css'

/**
 * KGVocabRow surface — iOS `KGVocabRow`(KGVocabPresenter.swift:201) 的 web 鏡像。
 *
 * iOS view tree（非 selecting 分支，Default / Highlighted）：
 *   HStack(spacing: inlineGap=8) {            // 無 checkmark（isSelecting=false）
 *     WordRow(viewData: entry.wordRowViewData(
 *       showsReviewState:false, showsSourceContext:false,
 *       showsDifficultyTier:false, showsReviewProgress:true))
 *   }
 *   .padding(.horizontal, listRowHorizontalInset=16)
 *   .padding(.vertical, AppSpacing.s1=4)
 *   .background { if isHighlighted: RoundedRectangle(sm=6).fill(accent.opacity(0.08)) }
 *   .padding(.horizontal, AppSpacing.s1=4)
 *
 * WordRow（WordRow.swift:62）：
 *   HStack(.center, spacing: wordRowHorizontalGap=10) {
 *     VStack(.leading, spacing: wordRowVerticalGap=4) {
 *       HStack(.firstTextBaseline, spacing: wordRowBaselineGap=6) {
 *         Text(word).font(rowWord = mono 18 semibold).foregroundStyle(primaryText)
 *         Text(pos).font(caption = sans 12 bold).foregroundStyle(tertiaryText)
 *       }
 *       Text(translation).font(body = sans 15).foregroundStyle(secondaryText).lineLimit(2)
 *     }
 *     Spacer(minLength: 0)
 *     // compact, !strikethrough, reviewProgress != nil（unlearned, ratio:nil）：
 *     VocabReviewProgressBar(progress) → Text(detailLabel="首輪 12h").monoLabel.secondaryText
 *   }
 *   .padding(.vertical, compactRowVerticalPadding=10)
 *
 * catalog 元件 scene 畫布透明（component-isolated，corner srgba 0）：`?crop=component`
 * 令 surface + phone-frame 透明、shots `transparent:true` omitBackground 截圖。
 * surface = scene 的 .padding(16)（scene wrapper）intrinsic box。
 */
export function KGVocabRowScreen({ scenario }: { scenario: ScenarioId<'kg-vocab-row'> }) {
  const fx = KG_VOCAB_ROW_FIXTURES[scenario]
  return (
    <div className="kg-vocab-row-surface">
      <div className={`kg-vocab-row${fx.isHighlighted ? ' kg-vocab-row--highlighted' : ''}`}>
        <div className="kg-vocab-row-content">
          <div className="kg-vocab-row-main">
            <div className="kg-vocab-row-head">
              <span className="kg-vocab-row-word">{fx.word}</span>
              <span className="kg-vocab-row-pos">{fx.partOfSpeech}</span>
            </div>
            <span className="kg-vocab-row-translation">{fx.translation}</span>
          </div>
          <span className="kg-vocab-row-detail">{fx.detailLabel}</span>
        </div>
      </div>
    </div>
  )
}
