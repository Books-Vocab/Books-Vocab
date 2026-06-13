import type { ScenarioId } from '../../harness/scenarios'
import { DocTextIcon } from './icons'
import { useWordDetailApiStore, useWordParam } from './useWordDetailApiStore'
import type { WordDetailPresentation } from './useWordDetailApiStore'
import './word-detail-sheet.css'

/**
 * WordDetailSheet surface — iOS `WordDetailSheet` 的 web 鏡像（loading state）。
 *
 * 視圖樹（iOS WordDetailSheet.body）：
 *   Group {
 *     if let presenterState { WordDetailPresenter(...) }       // snapshot 下未命中
 *     else {
 *       VocabStateMessageCard(title:"載入中", systemImage:"doc.text") {
 *         ProgressView().controlSize(.small)
 *       }
 *       .padding()                                              // SwiftUI 預設 ≈16
 *     }
 *   }
 *   .task(id:…) { await Task.yield(); state.refreshPresentation(...) }
 *
 * ⚠️ catalog 兩個 scene（Rich entry / Minimal entry）ref PNG **byte-identical**：
 *    presenter 在 `.task` yield 後才填充，snapshot 早於其完成 → 兩者皆停在
 *    else-branch 的「載入中」placeholder。故 web 兩個 scenario 渲染相同畫面。
 *
 * VocabStateMessageCard(.vocab) = AppStateMessageCard(.vocab)：
 *   AppSectionCard(padding 0)[
 *     VStack(.leading, spacing s2=8)[
 *       HStack(.firstTextBaseline, spacing s2=8)[
 *         Image(doc.text).font(iconSmall=symbol 12 medium)/accent ·
 *         Text("載入中").font(body=sans 15 semibold)/primaryText · Spacer ] ·
 *       ProgressView(.small)                                   // accessory
 *     ].padding(.h 14, .v 12)
 *   ].background(cardBackground).clipShape(radii.control=6)
 *    .overlay(stroke cardBorder lw1)
 *
 * catalog scene layout=.fill：透明畫布，card 由 .padding() 撐出 16pt 邊距、
 * 在可用區域垂直置中（ref 量測 card center native y≈1316 ≈ 螢幕中線）。
 * → manifest transparent:true、phone-frame 透明捕捉。
 */
export function WordDetailSheetScreen({
  scenario,
}: {
  scenario: ScenarioId<'word-detail-sheet'>
}) {
  const shell = new URLSearchParams(window.location.search).get('shell') === '1'
  if (shell) return <WordDetailSheetApi />
  return <WordDetailSheetFixture scenario={scenario} />
}

/** shell 路徑：拉真實卡片詳情並渲染 loaded view（loading/error fallback 沿用 placeholder）。 */
function WordDetailSheetApi() {
  const word = useWordParam()
  const store = useWordDetailApiStore(word)
  if (store.status === 'ready' && store.detail) {
    return <WordDetailLoaded detail={store.detail} />
  }
  // loading / error → 沿用載入態 placeholder（與 fixture 同一視覺，避免裸 error 字串）。
  return <WordDetailPlaceholder />
}

/** loaded view：完整詞條（meaning / collocations / inflections / linksByKind / tier）。 */
function WordDetailLoaded({ detail }: { detail: WordDetailPresentation }) {
  return (
    <div className="wds-surface wds-surface--loaded">
      <div className="wds-detail">
        <div className="wds-detail-head">
          <span className="wds-detail-word">{detail.word}</span>
          {detail.pos ? <span className="wds-detail-pos">{`${detail.pos}.`}</span> : null}
          {detail.difficultyTier ? (
            <span className="wds-detail-tier">{detail.difficultyTier}</span>
          ) : null}
        </div>

        <p className="wds-detail-meaning">{detail.meaning}</p>

        {detail.note ? <p className="wds-detail-note">{detail.note}</p> : null}

        {detail.examples.length > 0 ? (
          <div className="wds-detail-section">
            <span className="wds-detail-label">例句</span>
            {detail.examples.map((ex, i) => (
              <p key={i} className="wds-detail-example">
                {ex}
              </p>
            ))}
          </div>
        ) : null}

        {detail.inflections.length > 0 ? (
          <div className="wds-detail-section">
            <span className="wds-detail-label">變化形</span>
            <div className="wds-detail-pills">
              {detail.inflections.map((inf) => (
                <span key={inf} className="wds-detail-pill">
                  {inf}
                </span>
              ))}
            </div>
          </div>
        ) : null}

        {detail.collocations.length > 0 ? (
          <div className="wds-detail-section">
            <span className="wds-detail-label">搭配</span>
            <div className="wds-detail-pills">
              {detail.collocations.map((c) => (
                <span key={c} className="wds-detail-pill">
                  {c}
                </span>
              ))}
            </div>
          </div>
        ) : null}

        {detail.linkGroups.map((group) => (
          <div key={group.kind} className="wds-detail-section">
            <span className="wds-detail-label">{group.links[0]?.label ?? group.kind}</span>
            {group.links.map((l) => (
              <div key={l.id} className="wds-detail-link">
                <span className="wds-detail-link-word">{l.word}</span>
                <span className="wds-detail-link-reason">{l.reason}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}

/** Fixture-driven 載入態 placeholder（parity 路徑，DOM byte-identical）。 */
function WordDetailSheetFixture({
  scenario: _scenario,
}: {
  scenario: ScenarioId<'word-detail-sheet'>
}) {
  // 兩個 scenario 同畫面（載入態 placeholder）；scenario 僅供 manifest 對齊 ref 名。
  void _scenario
  return <WordDetailPlaceholder />
}

function WordDetailPlaceholder() {
  return (
    <div className="wds-surface">
      {/* VocabStateMessageCard(.vocab).padding() */}
      <div className="wds-state-card">
        {/* HStack(.firstTextBaseline, s2)[doc.text · "載入中" · Spacer] */}
        <div className="wds-state-row">
          <DocTextIcon className="wds-state-icon" />
          <span className="wds-state-title">載入中</span>
        </div>
        {/* accessory: ProgressView(.small) — iOS 系統 spinner（12 條輻射線） */}
        <span className="wds-spinner" aria-hidden="true">
          {Array.from({ length: 12 }).map((_, i) => (
            <i key={i} style={{ transform: `rotate(${i * 30}deg)` }} />
          ))}
        </span>
      </div>
    </div>
  )
}
