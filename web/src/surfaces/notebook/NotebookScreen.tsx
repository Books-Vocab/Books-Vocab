import type { CSSProperties } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import { NOTEBOOK_FIXTURES } from './fixtures'
import type { NotebookFixtureCard } from './fixtures'
import { FilterCircleIcon, PlusIcon, SparklesIcon } from './icons'
import './notebook.css'

/**
 * Notebook surface — iOS NotebookListView/NotebookListContent 的 web 重寫。
 * 幾何常數逐一對齊 iOS（見 notebook.css 的 px 註解）；結構順序 =
 * NotebookListView.body：large nav title → NotebookReviewActionBar（今日複習 +
 * CTA/filter/plus pill）→ AppAirDivider → LazyVStack book-row（NotebookCard）。
 */

function NotebookCard({ card }: { card: NotebookFixtureCard }) {
  const isEmpty = card.cardCount === 0
  // iOS: dark mode 自動 darken(coverColor, by: 0.55)（NotebookCard.coverColor）。
  // 兩主題的封面色 + 同色族加深 rule/dot 都先算好，CSS 依 data-theme 選用。
  const coverVars = {
    '--nb-cover-light': card.color,
    '--nb-cover-dark': darken(card.color, 0.55),
    '--nb-rule-light': darken(card.color, 0.5),
    // dark cover 本身已加深，rule 以「dark cover 再 darken 0.5」維持同色族對比
    '--nb-rule-dark': darken(darken(card.color, 0.55), 0.5),
  } as CSSProperties
  return (
    <div className="nb-card" style={coverVars}>
      {/* ── 左：cover 40% ── */}
      <div className="nb-card-cover">
        <div className="nb-card-cover-inner">
          <div className="nb-card-name-line">
            {card.isActive && <span className="nb-card-active-dot" />}
            <span className="nb-card-name">{card.name}</span>
          </div>
          {/* editorial rule — 1pt，cover 寬 × 0.3，darken 0.5 */}
          <span className="nb-card-rule" />
        </div>
        {/* 0.5pt 垂直 cardBorder rule（書背隱喻），cover 右緣 */}
        <span className="nb-card-spine" />
      </div>

      {/* ── 右：metadata ── */}
      <div className="nb-card-meta">
        {isEmpty ? (
          <span className="nb-card-empty">尚未加入單字</span>
        ) : (
          <>
            <div className="nb-card-stats">
              <span className="nb-card-count">{card.cardCount} 詞</span>
              {card.actionableCount > 0 && (
                <span className="nb-card-actionable">
                  <span className="nb-card-warning-dot" />
                  {card.actionableCount}
                </span>
              )}
            </div>
            <div className="nb-card-progress">
              <span
                className="nb-card-progress-fill"
                style={{ width: `${Math.round(card.reviewProgress * 100)}%` }}
              />
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export function NotebookScreen({ scenario }: { scenario: ScenarioId<'notebook'> }) {
  const fixture = NOTEBOOK_FIXTURES[scenario]
  return (
    <div className="notebook">
      <header className="nb-nav">
        <h1 className="nb-nav-title">單字本</h1>
      </header>
      <div className="nb-scroll">
        {/* Today Review action bar — mutedFill capsule 容器 + 三 pill */}
        <div className="nb-actionbar">
          <span className="nb-actionbar-title">今日複習</span>
          <span className="nb-actionbar-spacer" />
          {/* CTA pill — brandHero（黃），未學複習 sparkles + 總數 */}
          <span className="nb-pill nb-pill-cta">
            <SparklesIcon size={15} />
            <span className="nb-pill-num">{fixture.reviewTotal}</span>
          </span>
          {fixture.showFilter && (
            <span className="nb-pill nb-pill-tool">
              <FilterCircleIcon size={15} />
            </span>
          )}
          <span className="nb-pill nb-pill-tool">
            <PlusIcon size={15} />
          </span>
        </div>

        {/* AppAirDivider — hairline + dividerAir margin */}
        <div className="nb-air-divider" />

        <div className="nb-list">
          {fixture.cards.map((card) => (
            <NotebookCard key={card.name} card={card} />
          ))}
        </div>
      </div>
    </div>
  )
}

/**
 * NotebookPalette.darken — HSB brightness ×(1-amount)，hue/sat 保留。
 * 對齊 iOS active dot / editorial rule 的「同色族加深」。輸入 hex（#RRGGBB）。
 */
function darken(hex: string, amount: number): string {
  const n = parseInt(hex.slice(1), 16)
  const r = (n >> 16) & 0xff
  const g = (n >> 8) & 0xff
  const b = n & 0xff
  const [h, s, v] = rgbToHsv(r, g, b)
  const [nr, ng, nb] = hsvToRgb(h, s, v * (1 - amount))
  return `rgb(${nr}, ${ng}, ${nb})`
}

function rgbToHsv(r: number, g: number, b: number): [number, number, number] {
  const rn = r / 255, gn = g / 255, bn = b / 255
  const max = Math.max(rn, gn, bn), min = Math.min(rn, gn, bn)
  const d = max - min
  let h = 0
  if (d !== 0) {
    if (max === rn) h = ((gn - bn) / d) % 6
    else if (max === gn) h = (bn - rn) / d + 2
    else h = (rn - gn) / d + 4
    h *= 60
    if (h < 0) h += 360
  }
  const s = max === 0 ? 0 : d / max
  return [h, s, max]
}

function hsvToRgb(h: number, s: number, v: number): [number, number, number] {
  const c = v * s
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1))
  const m = v - c
  let rp = 0, gp = 0, bp = 0
  if (h < 60) [rp, gp, bp] = [c, x, 0]
  else if (h < 120) [rp, gp, bp] = [x, c, 0]
  else if (h < 180) [rp, gp, bp] = [0, c, x]
  else if (h < 240) [rp, gp, bp] = [0, x, c]
  else if (h < 300) [rp, gp, bp] = [x, 0, c]
  else [rp, gp, bp] = [c, 0, x]
  return [Math.round((rp + m) * 255), Math.round((gp + m) * 255), Math.round((bp + m) * 255)]
}
