import type { ScenarioId } from '../../harness/scenarios'
import { GraphNodesIcon, XmarkIcon } from './icons'
import {
  KNOWLEDGE_GRAPH_FIXTURES,
  REVIEW_GRADIENT_BAR_STOPS,
  LEGEND_COLORS,
  SETTINGS_FORCES_ROWS,
  SETTINGS_DISPLAY_ROWS,
  type SliderRowFixture,
} from './fixtures'
import './vocab-knowledge-graph.css'

/**
 * Vocabulary · Knowledge Graph surface — iOS `KnowledgeGraphPresenter` 的 web 鏡像。
 *
 * 視圖樹（KnowledgeGraphPresenter.swift）：
 *   VocabSceneShell(phase) {
 *     ZStack { pageBackground
 *       ZStack(bottom) { graphView(GraphWebView, masked)
 *         VStack { HStack{Spacer; graphLegend} ; Spacer }   // 右上 legend chip
 *         if showsSettings: settingsOverlay                  // 底部 drawer 卡
 *       }
 *     }
 *   }
 * graphScenePhase：emptyState != nil → `.empty`（VocabEmptyStateCard，無 legend）；
 * 否則 `.content`（graph canvas + legend）。
 *
 * 關鍵：`GraphWebView`（WKWebView force-graph）在 catalog 靜態快照不繪節點/邊，
 * 故 content 態 ref 的 graph 區 = 全 page-bg；web 僅還原 page-bg + legend(+settings)。
 *
 * catalog ref = .fill 全裝置幀（1179×2556，corner srgba(247,246,243,1)=page-bg，
 * 不透明）→ 全 phone-frame 捕捉（無 crop=component、無 transparent）：surface 撐滿
 * phone-frame、bg=page-bg。legend/settings 以絕對定位釘在 ref 量得的像素位置。
 */
export function VocabKnowledgeGraphScreen({
  scenario,
}: {
  scenario: ScenarioId<'vocab-knowledge-graph'>
}) {
  const fixture = KNOWLEDGE_GRAPH_FIXTURES[scenario]

  if (fixture.empty) {
    // VocabSceneShell `.empty` → centeredWrapper{ VocabEmptyStateCard }，無 legend。
    return (
      <div className="vkg-surface vkg-surface--empty">
        <div className="vkg-empty-card">
          <div className="vkg-empty-content">
            <GraphNodesIcon className="vkg-empty-icon" size={30} strokeWidth={1.4} />
            <div className="vkg-empty-title">{fixture.empty.title}</div>
            <div className="vkg-empty-description">{fixture.empty.description}</div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="vkg-surface">
      {/* GraphWebView：快照不繪節點，留白即可（page-bg）。 */}
      {fixture.showsLegend ? <GraphLegend /> : null}
      {fixture.showsSettings ? <SettingsOverlay /> : null}
    </div>
  )
}

/** graphLegend：漸層條 + 三色標籤 + 灰點圖例，置右上、cardBackground.opacity(0.85) chip。 */
function GraphLegend() {
  return (
    <div className="vkg-legend">
      <div className="vkg-legend-bar">
        {REVIEW_GRADIENT_BAR_STOPS.map((c, i) => (
          // 資料色（ReviewGradient），非品牌 token：token-allow review-gradient stop
          <span key={i} className="vkg-legend-bar-seg" style={{ background: c }} />
        ))}
      </div>

      <div className="vkg-legend-labels">
        {/* token-allow ReviewGradient.color(for:) data colors */}
        <span className="vkg-legend-label" style={{ color: LEGEND_COLORS.safe }}>
          安全
        </span>
        <span className="vkg-legend-spacer" />
        <span className="vkg-legend-label" style={{ color: LEGEND_COLORS.due }}>
          到期
        </span>
        <span className="vkg-legend-spacer" />
        <span className="vkg-legend-label" style={{ color: LEGEND_COLORS.overdue }}>
          逾期
        </span>
      </div>

      <div className="vkg-legend-unlearned">
        <span className="vkg-legend-dot" />
        <span className="vkg-legend-unlearned-text">未學習 / 封存</span>
      </div>
    </div>
  )
}

/** settingsOverlay：VocabCard(padding 0) — header + divider + 力/顯示 section + toggle。 */
function SettingsOverlay() {
  return (
    <div className="vkg-settings">
      <div className="vkg-settings-card">
        {/* VocabOverlayHeader：[重設 inline] [Label(關聯圖 + glyph)] Spacer [xmark chrome] */}
        <div className="vkg-overlay-header">
          <button type="button" className="vkg-inline-action">
            重設
          </button>
          <span className="vkg-overlay-title">
            <GraphNodesIcon className="vkg-overlay-title-icon" size={13} strokeWidth={1.5} />
            <span>關聯圖</span>
          </span>
          <span className="vkg-overlay-spacer" />
          <span className="vkg-chrome-button" aria-label="關閉">
            <XmarkIcon className="vkg-chrome-icon" size={15} strokeWidth={1.6} />
          </span>
        </div>

        <div className="vkg-overlay-divider" />

        <div className="vkg-settings-body">
          <div className="vkg-settings-section">
            <SectionHeader title="力" />
            {SETTINGS_FORCES_ROWS.map((row) => (
              <SliderRow key={row.label} {...row} />
            ))}
          </div>

          <div className="vkg-card-section-divider" />

          <div className="vkg-settings-section">
            <SectionHeader title="顯示" />
            {SETTINGS_DISPLAY_ROWS.map((row) => (
              <SliderRow key={row.label} {...row} />
            ))}

            {/* Toggle(孤立節點)：caption label + .switch（off = muted track）。 */}
            <div className="vkg-toggle-row">
              <span className="vkg-toggle-label">孤立節點</span>
              <span className="vkg-toggle-switch" role="switch" aria-checked="false" aria-label="孤立節點">
                <span className="vkg-toggle-knob" />
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

/** VocabSectionHeader：caption(12 bold) tracking 0.5 / tertiaryText。 */
function SectionHeader({ title }: { title: string }) {
  return (
    <div className="vkg-section-header">
      <span className="vkg-section-header-title">{title}</span>
    </div>
  )
}

/** VocabSliderRow：[caption label w64] [Slider tint-fill] [monoLabel value w42]。 */
function SliderRow({ label, fill, valueText }: SliderRowFixture) {
  return (
    <div className="vkg-slider-row">
      <span className="vkg-slider-label">{label}</span>
      <span
        className="vkg-slider-track"
        role="slider"
        aria-valuenow={Math.round(fill * 100)}
        aria-label={label}
      >
        <span className="vkg-slider-fill" style={{ width: `${fill * 100}%` }} />
      </span>
      <span className="vkg-slider-value">{valueText}</span>
    </div>
  )
}
