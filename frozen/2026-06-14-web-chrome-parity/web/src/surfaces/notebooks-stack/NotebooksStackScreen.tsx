import type { CSSProperties } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import { NOTEBOOKS_STACK_FIXTURES } from './fixtures'
import type { NotebooksStackItem } from './fixtures'
import './notebooks-stack.css'

/**
 * Notebooks · Stack surface — iOS `NotebookCard`(style:.grid，NotebookListScenarios
 * catalog)的 web 鏡像。scene = `.fill` 全裝置幀（1179×2556）。
 *
 * 注意：`NotebookCard.body` 不依 style 分支，亦**未**走 NotebookStackedCoverView——
 * body 直接畫扁平 coverColor + noise(0.04) + pattern(dots, 0.12) + serif name(17) +
 * active dot + rule，右側 metadata(N 詞 mono10 + actionable caption12 + ProgressCapsule h=4)。
 * coverArea/metadataArea 為 dead path（編到但 grid body 未用）。
 *
 * 兩種 scene：
 * - single（State/Depth/empty）：card.frame(maxWidth:200) 左上對齊於 page-bg 內容窄欄，
 *   周圍透明（ref corner srgba 0,0,0,0 → shots transparent:true / phone-frame 透明）。
 * - grid（D1 cover composition basic）：LazyVGrid 2-up，page-bg 全幅鋪滿
 *   （ref corner = page-bg 不透明 → 無 transparent）。
 */

function NotebookCard({ card }: { card: NotebooksStackItem }) {
  const isEmpty = card.cardCount === 0
  // 封面黃點數字 = dueCount + unlearnedCount（actionableCount，與封面/今日複習同口徑）
  const actionableCount = card.dueCount + card.unlearnedCount
  const totalSynced = card.dueCount + card.unlearnedCount + card.reviewedCount
  const reviewProgress = totalSynced > 0 ? card.reviewedCount / totalSynced : 0

  // iOS: dark mode 自動 darken(coverColor, by:0.55)；rule/dot 走 darken 0.5。
  const coverVars = {
    '--nb-cover-light': card.color,
    '--nb-cover-dark': darken(card.color, 0.55),
    '--nb-rule-light': darken(card.color, 0.5),
    '--nb-rule-dark': darken(darken(card.color, 0.55), 0.5),
  } as CSSProperties

  return (
    <div className="nbs-card" style={coverVars} data-name={card.name}>
      {/* ── 左：cover 40% ── */}
      <div className="nbs-card-cover" data-pattern={card.pattern ?? undefined}>
        <div className="nbs-card-cover-inner">
          <div className="nbs-card-name-line">
            {card.isActive && <span className="nbs-card-active-dot" />}
            <span className="nbs-card-name">{card.name}</span>
          </div>
          {/* editorial rule — 1pt，cover 寬 × 0.3，darken 0.5 */}
          <span className="nbs-card-rule" />
        </div>
        {/* 0.5pt 垂直 cardBorder rule（書背隱喻），cover 右緣 */}
        <span className="nbs-card-spine" />
      </div>

      {/* ── 右：metadata ── */}
      <div className="nbs-card-meta">
        {isEmpty ? (
          <span className="nbs-card-empty">尚未加入單字</span>
        ) : (
          <>
            <div className="nbs-card-stats">
              <span className="nbs-card-count">{card.cardCount} 詞</span>
              {actionableCount > 0 && (
                <span className="nbs-card-actionable">
                  <span className="nbs-card-warning-dot" />
                  {/* iOS Text("\(Int)") → LocalizedStringKey 群組分隔；此處 20 無分隔差異 */}
                  {actionableCount.toLocaleString('en-US')}
                </span>
              )}
            </div>
            <div className="nbs-card-progress">
              <span
                className="nbs-card-progress-fill"
                style={{ width: `${Math.round(reviewProgress * 100)}%` }}
              />
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export function NotebooksStackScreen({ scenario }: { scenario: ScenarioId<'notebooks-stack'> }) {
  const fixture = NOTEBOOKS_STACK_FIXTURES[scenario]
  return (
    <div className="notebooks-stack" data-layout={fixture.layout}>
      <div className={fixture.layout === 'grid' ? 'nbs-grid' : 'nbs-single'}>
        {fixture.cards.map((card) => (
          <NotebookCard key={card.name} card={card} />
        ))}
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
