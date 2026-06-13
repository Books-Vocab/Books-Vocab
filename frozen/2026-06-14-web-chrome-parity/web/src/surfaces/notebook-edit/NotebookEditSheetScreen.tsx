import type { ScenarioId } from '../../harness/scenarios'
import { CirclesOverlay, PatternOverlay } from '../notebook-cover/icons'
import {
  NOTEBOOK_DEFAULT_HEX,
  NOTEBOOK_EDIT_FIXTURES,
  NOTEBOOK_PALETTE,
  NOTEBOOK_PATTERNS,
} from './fixtures'
import { CheckmarkCircleFillIcon, CheckmarkIcon, PhotoIcon } from './icons'
import './notebook-edit.css'

/**
 * NotebookEditSheet surface — iOS `NotebookEditSheet`（新建/編輯單字本 sheet）的
 * web 鏡像。
 *
 * iOS = NavigationStack{ Form{ 5 Section } }，inline nav title、grouped inset list：
 *   1. 封面預覽 NotebookCoverView(color/pattern/name, height 100, radius card=8)
 *   2. TextField(單字本名稱)
 *   3. 顏色 — LazyVGrid(adaptive 36, spacing chipPaddingH=10) of 12 色圈(32)，selected 白勾
 *   4. 圖案 — ScrollView(.h) HStack(s2=8)[無 + 6 pattern tile(48×36)]，selected 白勾圈
 *   5. 自訂圖片 — PhotosPicker Label(photo, 選擇圖片)
 *
 * grouped 背景 systemGroupedBackground #F2F2F7、card secondarySystemGroupedBackground 白、
 * card 水平 inset 16pt（量自 ref：card 左緣 16pt、cover top ≈153pt = status59+navBar44+form top）。
 * nav title 在 grouped 頂幾近隱形（量測 ≈244 on 242 bg）→ 以極淡色渲染。
 *
 * catalog scene = .fill opaque（grouped bg 不透明）→ 全 phone-frame 不透明捕捉。
 * pattern overlay 直接複用 notebook-cover/icons（同一 NotebookCoverPattern 幾何）。
 */
export function NotebookEditSheetScreen({
  scenario,
}: {
  scenario: ScenarioId<'notebook-edit'>
}) {
  const fx = NOTEBOOK_EDIT_FIXTURES[scenario]
  const coverColor = fx.selectedColor ?? NOTEBOOK_DEFAULT_HEX
  const coverName = fx.name.length === 0 ? '預覽' : fx.name

  return (
    <div className="nbe-surface">
      {/* inline nav bar — 標題置中、極淡 */}
      <div className="nbe-nav">
        <div className="nbe-nav-title">{fx.isCreating ? '新增單字本' : '編輯單字本'}</div>
      </div>

      <div className="nbe-form">
        {/* Section 1 — 封面預覽 */}
        <section className="nbe-section nbe-section--cover">
          <div className="nbe-card nbe-card--cover">
            <div className="nbe-cover" style={{ background: coverColor }}>
              {fx.selectedPattern === 'circles' ? (
                <CirclesOverlay />
              ) : fx.selectedPattern ? (
                <PatternOverlay pattern={fx.selectedPattern} />
              ) : null}
              <span className="nbe-cover-name">{coverName}</span>
            </div>
          </div>
        </section>

        {/* Section 2 — 名稱 */}
        <section className="nbe-section">
          <div className="nbe-card nbe-card--field">
            {fx.name.length === 0 ? (
              <span className="nbe-field-placeholder">單字本名稱</span>
            ) : (
              <span className="nbe-field-text">{fx.name}</span>
            )}
          </div>
        </section>

        {/* Section 3 — 顏色 */}
        <section className="nbe-section">
          <div className="nbe-section-header">顏色</div>
          <div className="nbe-card">
            <div className="nbe-color-grid">
              {NOTEBOOK_PALETTE.map((c) => (
                <div key={c.hex} className="nbe-swatch" style={{ background: c.hex }}>
                  {fx.selectedColor === c.hex ? (
                    <CheckmarkIcon className="nbe-swatch-check" />
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Section 4 — 圖案 */}
        <section className="nbe-section">
          <div className="nbe-section-header">圖案</div>
          <div className="nbe-card">
            <div className="nbe-pattern-row">
              <PatternTile
                label="無"
                selected={fx.selectedPattern === null}
                fill="muted"
              />
              {NOTEBOOK_PATTERNS.map((p) => (
                <PatternTile
                  key={p.id}
                  label={p.label}
                  selected={fx.selectedPattern === p.id}
                  fill={coverColor}
                  pattern={p.id}
                />
              ))}
            </div>
          </div>
        </section>

        {/* Section 5 — 自訂圖片 */}
        <section className="nbe-section">
          <div className="nbe-section-header">自訂圖片</div>
          <div className="nbe-card nbe-card--field">
            <span className="nbe-image-label">
              <PhotoIcon className="nbe-image-icon" />
              選擇圖片
            </span>
          </div>
        </section>
      </div>
    </div>
  )
}

function PatternTile({
  label,
  selected,
  fill,
  pattern,
}: {
  label: string
  selected: boolean
  fill: string
  pattern?: import('../notebook-cover/fixtures').CoverPattern
}) {
  return (
    <div className="nbe-pattern-tile">
      <div
        className="nbe-pattern-swatch"
        style={fill === 'muted' ? undefined : { background: fill }}
        data-muted={fill === 'muted' ? '1' : undefined}
      >
        {pattern === 'circles' ? (
          <CirclesOverlay />
        ) : pattern ? (
          <PatternOverlay pattern={pattern} />
        ) : null}
        {selected ? <CheckmarkCircleFillIcon className="nbe-pattern-check" /> : null}
      </div>
      <span className="nbe-pattern-label">{label}</span>
    </div>
  )
}
