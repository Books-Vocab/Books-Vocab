import type { ScenarioId } from '../../harness/scenarios'

/**
 * Vocabulary · Knowledge Graph fixtures — 逐字對齊 iOS
 * `KnowledgeGraphPresenterPreviewData`（VocabScenarios.swift）。
 *
 * 關鍵觀察：catalog .fill scene 中 `GraphWebView`（WKWebView force-graph）在
 * 靜態快照時**不繪製任何節點/邊**（ref 的 graph canvas 全為 page-bg）。因此各
 * scene 可還原的只有：
 *   - with-data / settings-open：右上 graphLegend chip（漸層條 + 三色標籤 + 灰點）。
 *   - settings-open：再疊底部 settingsOverlay 卡（重設/關聯圖 header + 力/顯示
 *     兩 section 的 slider rows + 孤立節點 toggle）。
 *   - empty / no-links：VocabSceneShell `.empty` → 居中 VocabEmptyStateCard（無 legend）。
 *
 * legend 漸層條 = ReviewGradientBar：20 段 Rectangle，ratio = i/19*3，色 =
 * ReviewGradient.color(for:)（HSL 內插 → hslToHSB → Color(HSB)）。以下 20 色為
 * Swift 路徑離線量算結果（round half-away-from-zero）。標籤色同 color(for:)：
 *   安全 ratio 0 → #328F70、到期 ratio 1.0 → #BE9C37、逾期 ratio 2.5 → #912B6E。
 */

export const REVIEW_GRADIENT_BAR_STOPS = [
  '#328F70', '#399365', '#3F9857', '#479B46', '#65A047',
  '#95A941', '#B8A339', '#BC8C31', '#BA7229', '#B56028',
  '#AF5229', '#AA462A', '#A53A2A', '#9F2B2C', '#9A2B45',
  '#952B5C', '#902B71', '#8C2B83', '#7A2B87', '#622B82',
]

export const LEGEND_COLORS = {
  safe: '#328F70', // ReviewGradient.color(for: 0)
  due: '#BE9C37', // ReviewGradient.color(for: 1.0)
  overdue: '#912B6E', // ReviewGradient.color(for: 2.5)
}

export interface SliderRowFixture {
  label: string
  /** filled 比例 0..1（= (value - lo) / (hi - lo)） */
  fill: number
  /** 右側值文字（已套 iOS format） */
  valueText: string
}

export interface KnowledgeGraphFixture {
  /** 是否顯示右上 legend chip（content 態 = true；empty/no-links = false） */
  showsLegend: boolean
  /** 是否顯示底部 settings overlay 卡 */
  showsSettings: boolean
  /** empty 態文案（非 nil 時渲染 VocabEmptyStateCard，且不顯示 legend） */
  empty?: { title: string; description: string }
}

// PreviewData force 值：centerForce 0.24 / repelForce 0.76 / linkForce 0.32 /
// linkDistance 120 (20...300) / nodeSize 4.2 (1...10) / linkThickness 1.1 (0.5...3)。
export const SETTINGS_FORCES_ROWS: SliderRowFixture[] = [
  { label: '向心力', fill: 0.24, valueText: '0.24' }, // 0...1, %.2f
  { label: '排斥力', fill: 0.76, valueText: '0.76' },
  { label: '連結強度', fill: 0.32, valueText: '0.32' },
  { label: '連結距離', fill: (120 - 20) / (300 - 20), valueText: '120' }, // 20...300, %.0f
]

export const SETTINGS_DISPLAY_ROWS: SliderRowFixture[] = [
  { label: '節點大小', fill: (4.2 - 1) / (10 - 1), valueText: '4.2' }, // 1...10, %.1f
  { label: '連結粗細', fill: (1.1 - 0.5) / (3 - 0.5), valueText: '1.1' }, // 0.5...3, %.1f
]

export const KNOWLEDGE_GRAPH_FIXTURES: Record<
  ScenarioId<'vocab-knowledge-graph'>,
  KnowledgeGraphFixture
> = {
  'with-data': { showsLegend: true, showsSettings: false },
  'settings-open': { showsLegend: true, showsSettings: true },
  empty: {
    showsLegend: false,
    showsSettings: false,
    empty: {
      title: '知識圖譜為空',
      description: '尚無已收錄單字，或尚未與伺服器同步。',
    },
  },
  'no-links': {
    showsLegend: false,
    showsSettings: false,
    empty: {
      title: '尚無知識連結',
      description: '持續收錄相關單字，系統會自動建立關聯。或在設定中開啟「孤立節點」以瀏覽所有單字。',
    },
  },
}
