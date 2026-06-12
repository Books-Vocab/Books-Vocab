import type { ScenarioId } from '../../harness/scenarios'
import { REVIEW_FOLD_PAPER_FIXTURES, SAMPLE_CARD } from './fixtures'
import './review-fold-paper.css'

/**
 * Review Fold · Paper Fold — iOS `PaperFoldModifier` 套在 `sampleCard` 上的 web 鏡像。
 *
 * iOS scene（ReviewFoldScenarios.foldedCard，layout = .fill）：
 *   AppThemeContainer { sampleCard(serendipity / 機緣巧合)
 *     .modifier(PaperFoldModifier(progress)) .padding(40) }
 * sampleCard = VStack(spacing 8, maxWidth ∞)[
 *   Text(title3.semibold) · Text(subheadline / secondary) · Text(footnote / tertiary)]
 *   .padding(24) .background(RoundedRectangle(radii.card=8) fill cardBackground)
 *   .overlay(RoundedRectangle stroke cardBorder 1px)。
 *
 * PaperFoldModifier（progress 0=全摺 1=全展，anchor=.top）：
 *   .scaleEffect(y: max(progress,0.02), anchor:.top)
 *   .rotation3DEffect(.degrees((1-progress)*-88), axis(1,0,0), anchor:.top, perspective:0.86)
 *   .opacity(progress)
 *   .offset(y: (1-progress) * -12)            // paperFoldOffsetY = 12
 *
 * catalog scene = .fill（1179×2556，畫布透明 corner alpha≈0）：card+padding(40) 於整
 * frame 內**垂直置中**。故走**全 phone-frame 透明捕捉**（無 crop=component），surface
 * 撐滿、justify center；phone-frame + surface 透明，shots transparent:true。
 *
 * SwiftUI rotation3DEffect 的 perspective p 與 CSS perspective(d) 關係：CSS d 越小透視越強，
 * SwiftUI p 為 m34 縮放因子；以卡片自身度量近似 d = cardWidth / p（見 css comment）。
 */
export function ReviewFoldPaperScreen({
  scenario,
}: {
  scenario: ScenarioId<'review-fold-paper'>
}) {
  const { progress } = REVIEW_FOLD_PAPER_FIXTURES[scenario]
  // anchor .top：scaleY 從頂緣壓縮；rotation3D 繞 X 軸（top anchor）；opacity + 上移 offset。
  // iOS modifier 鏈順序 = scaleEffect（內層，先套）→ rotation3DEffect（外層，後套），
  // 故 CSS transform 須 scaleY 最右（先套）、rotateX 居中：旋轉作用在已壓縮的卡片上。
  // 順序顛倒（rotate 先）會在中段（progress≈0.75）產生最大幾何偏差。
  const scaleY = Math.max(progress, 0.02)
  const rotX = (1 - progress) * -88
  const offsetY = (1 - progress) * -12

  return (
    <div className="review-fold-paper-surface">
      <div className="review-fold-paper-stage">
        <div
          className="review-fold-paper-card"
          style={{
            transform: `translateY(${offsetY}px) scaleY(${scaleY}) rotateX(${rotX}deg)`,
            opacity: progress,
          }}
        >
          <div className="review-fold-paper-title">{SAMPLE_CARD.title}</div>
          <div className="review-fold-paper-subtitle">{SAMPLE_CARD.subtitle}</div>
          <div className="review-fold-paper-body">{SAMPLE_CARD.body}</div>
        </div>
      </div>
    </div>
  )
}
