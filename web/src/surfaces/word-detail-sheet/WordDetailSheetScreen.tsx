import type { ScenarioId } from '../../harness/scenarios'
import { DocTextIcon } from './icons'
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
  scenario: _scenario,
}: {
  scenario: ScenarioId<'word-detail-sheet'>
}) {
  // 兩個 scenario 同畫面（載入態 placeholder）；scenario 僅供 manifest 對齊 ref 名。
  void _scenario

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
