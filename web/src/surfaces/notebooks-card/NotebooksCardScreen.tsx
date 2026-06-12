import type { CSSProperties } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import { NOTEBOOKS_CARD_FIXTURES } from './fixtures'
import type { NotebooksCardItem } from './fixtures'
import './notebooks-card.css'

/**
 * Notebooks · Card surface — iOS `NotebookCard`（NotebooksScenarios catalog）的
 * web 鏡像。component crop（catalog ref 1179×264，corner = page-bg 不透明）。
 *
 * scene = NotebooksScenarios.cardSheet / gridSheet：pageTopInset=16、
 * pageHorizontalInset=s5(20)、grid spacing=s6(24)。crop 截 `.notebooks-card`
 * 容器整框（含 page-bg + 上/側 inset），對齊 ref 內容緊裁。
 *
 * 卡片 DOM/CSS 結構與既有 `notebook` surface 的 NotebookCard 完全一致
 * （HStack book-row 72pt、cover 40%、serif 17 name + active dot + rule、
 * metadata：N 詞 mono(10) + actionable caption(12) + ProgressCapsule h=4），
 * 唯外層排列改 hero(VStack 單卡) / grid(2-col adaptive)。
 */

function NotebookCard({ card }: { card: NotebooksCardItem }) {
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
    <div className="nbc-card" style={coverVars} data-name={card.name}>
      {/* ── 左：cover 40% ── */}
      <div className="nbc-card-cover">
        <div className="nbc-card-cover-inner">
          <div className="nbc-card-name-line">
            {card.isActive && <span className="nbc-card-active-dot" />}
            <span className="nbc-card-name">{card.name}</span>
          </div>
          {/* editorial rule — 1pt，cover 寬 × 0.3，darken 0.5 */}
          <span className="nbc-card-rule" />
        </div>
        {/* 0.5pt 垂直 cardBorder rule（書背隱喻），cover 右緣 */}
        <span className="nbc-card-spine" />
      </div>

      {/* ── 右：metadata ── */}
      <div className="nbc-card-meta">
        {isEmpty ? (
          <span className="nbc-card-empty">尚未加入單字</span>
        ) : (
          <>
            <div className="nbc-card-stats">
              <span className="nbc-card-count">{card.cardCount} 詞</span>
              {actionableCount > 0 && (
                <span className="nbc-card-actionable">
                  <span className="nbc-card-warning-dot" />
                  {/* iOS Text("\(Int)")：Int 插入 LocalizedStringKey → locale 群組分隔
                      （1801 → "1,801"）。cardCount 走 L10n.format %@（預先 stringify）
                      無群組（"7000 詞"），故兩數字分隔行為不同。 */}
                  {actionableCount.toLocaleString('en-US')}
                </span>
              )}
            </div>
            <div className="nbc-card-progress">
              <span
                className="nbc-card-progress-fill"
                style={{ width: `${Math.round(reviewProgress * 100)}%` }}
              />
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export function NotebooksCardScreen({ scenario }: { scenario: ScenarioId<'notebooks-card'> }) {
  const fixture = NOTEBOOKS_CARD_FIXTURES[scenario]
  return (
    <div className="notebooks-card" data-layout={fixture.layout}>
      <div className={fixture.layout === 'grid' ? 'nbc-grid' : 'nbc-stack'}>
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
