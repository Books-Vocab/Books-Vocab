import type { ScenarioId } from '../../harness/scenarios'
import { WORD_EDIT_FIXTURES } from './fixtures'
import './word-edit.css'

/**
 * WordEdit surface — iOS `WordEditSheet`（編輯詞條翻譯 / 教學筆記的 sheet）的 web 鏡像。
 *
 * iOS = NavigationStack{ ScrollView{ VStack(alignment:.leading, spacing: sectionGap)[
 *   editSection("翻譯結果", $draftTranslation)
 *   editSection("教學筆記", $draftExplanation)
 * ] }.padding(cardPadding=18) }
 *   .vocabCanvasBackground()（page-bg 米色 #f7f6f3）
 *   .navigationTitle(entry.word).inlineNavigationBarTitle()  ← serif、近白、截斷
 *
 * editSection = VStack(alignment:.leading, spacing: inlineGap=8)[
 *   Text(title).font(caption = sans 12 bold).foregroundStyle(secondaryText)
 *   TextEditor(text).font(body = sans 15).foregroundStyle(primaryText)
 *     .padding(inlineGap=8).frame(minHeight 80)
 *     .background(RoundedRectangle(cardCornerRadius=8) fill(cardBackground)
 *                 .overlay(stroke(cardBorder.opacity(0.5), lineWidth 1)))
 * ]
 *
 * 量自 ref（1179×2556 native，÷3 = pt）：page-bg #f7f6f3、card 白 #fff、
 * card 水平 inset 18pt（cardPadding）、card border 近 #f4f4f4（cardBorder×0.5）、
 * caption secondaryText #6b6a65、body primaryText #37352f、nav title serif 近白。
 *
 * catalog scene = .fill opaque（page-bg 不透明，alpha-mean=1）→ 全 phone-frame 不透明捕捉，
 * 無 transparent flag。
 */
export function WordEditScreen({
  scenario,
}: {
  scenario: ScenarioId<'word-edit'>
}) {
  const fx = WORD_EDIT_FIXTURES[scenario]

  return (
    <div className="we-surface">
      {/* inline nav bar — entry.word，serif、近白、置中、過長截斷 */}
      <div className="we-nav">
        <div className="we-nav-title">{fx.word}</div>
      </div>

      <div className="we-form">
        <EditSection title="翻譯結果" text={fx.translation} />
        <EditSection title="教學筆記" text={fx.explanation} />
      </div>
    </div>
  )
}

function EditSection({ title, text }: { title: string; text: string }) {
  return (
    <section className="we-section">
      <div className="we-caption">{title}</div>
      <div className="we-editor">{text}</div>
    </section>
  )
}
