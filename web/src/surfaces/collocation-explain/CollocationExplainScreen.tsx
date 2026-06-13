import type { ScenarioId } from '../../harness/scenarios'
import { COLLOCATION_EXPLAIN_FIXTURES } from './fixtures'
import { TrashIcon, XmarkIcon } from './icons'
import { useCollocationExplainApiStore } from './useCollocationExplainApiStore'
import './collocation-explain.css'

/**
 * CollocationExplainSheet surface — iOS `CollocationExplainSheet`（.loaded phase）
 * 的 web 鏡像。
 *
 * 視圖樹：VStack(align .leading, spacing s3=12)[
 *   Text(collocation).font(detailWord = mono 27 semibold)/primaryText ·
 *   CardSectionDivider(hPadding 0 → 全寬 0.5pt /divider) ·
 *   contentSection(.loaded = Text(explanation).font(body = sans 15)/secondaryText
 *     .fixedSize(v).lineSpacing(3)) ·
 *   Spacer() ·
 *   footerToolbar(HStack spacing s1=4)[Spacer · trash(destructive) · xmark]
 * ]
 * .padding(.h panelHorizontalInset=18).padding(.top s5=20).padding(.bottom panelBottomInset=16)
 *
 * 三場景 existingExplanation 皆非 nil → footer 顯示 trash + xmark、無 save 鈕。
 *
 * catalog scene layout = .fill（1179×2556，畫布透明 corner srgba 0,0,0,0）：
 * 元件撐滿整 phone-frame，內容自頂部排列、footer 靠 Spacer 推到底部。故走全
 * phone-frame 透明捕捉（非 crop=component）：surface 撐滿、phone-frame 透明、
 * shots transparent:true。
 */
export function CollocationExplainScreen({
  scenario,
}: {
  scenario: ScenarioId<'collocation-explain'>
}) {
  const shell = new URLSearchParams(window.location.search).get('shell') === '1'
  if (shell) return <CollocationExplainApi />
  return <CollocationExplainFixture scenario={scenario} />
}

/** shell 路徑：把 nav 帶進來的搭配詞丟給 translate.explain，渲染即時解釋。 */
function CollocationExplainApi() {
  const store = useCollocationExplainApiStore()
  // loading：無解釋文，顯示載入態提示；error：缺 collocation/呼叫失敗 → 沿用提示，
  // 避免裸 error 字串（與其他 vocab surface 的 fallback 一致）。
  const collocation = store.collocation ?? ''
  const explanation =
    store.status === 'ready'
      ? store.explanation
      : store.status === 'loading'
        ? '正在產生解釋…'
        : '無法載入解釋，請稍後再試。'
  return <CollocationExplainBody collocation={collocation} explanation={explanation} />
}

/** Fixture-driven 唯讀 sheet（parity 路徑，DOM byte-identical）。 */
function CollocationExplainFixture({
  scenario,
}: {
  scenario: ScenarioId<'collocation-explain'>
}) {
  const fixture = COLLOCATION_EXPLAIN_FIXTURES[scenario]
  return (
    <CollocationExplainBody collocation={fixture.collocation} explanation={fixture.explanation} />
  )
}

/** 共用畫面本體（fixture / API 兩條路共用）。 */
function CollocationExplainBody({
  collocation,
  explanation,
}: {
  collocation: string
  explanation: string
}) {
  return (
    <div className="collocation-explain-surface">
      <div className="collocation-explain-title">{collocation}</div>

      <div className="collocation-explain-divider" />

      <div className="collocation-explain-body">{explanation}</div>

      <div className="collocation-explain-spacer" />

      <div className="collocation-explain-footer">
        <div className="collocation-explain-footer-spacer" />
        <button
          type="button"
          className="collocation-explain-chrome-button"
          aria-label="trash"
        >
          <span className="collocation-explain-chrome-card">
            <TrashIcon className="collocation-explain-glyph collocation-explain-glyph--destructive" />
          </span>
        </button>
        <button
          type="button"
          className="collocation-explain-chrome-button"
          aria-label="Close"
        >
          <span className="collocation-explain-chrome-card">
            <XmarkIcon className="collocation-explain-glyph" />
          </span>
        </button>
      </div>
    </div>
  )
}
