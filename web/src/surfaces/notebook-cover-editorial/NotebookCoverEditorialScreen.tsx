import type { ScenarioId } from '../../harness/scenarios'
import {
  NOTEBOOK_COVER_EDITORIAL_FIXTURES,
  type EditorialCoverItem,
} from './fixtures'
import './notebook-cover-editorial.css'

/**
 * Notebook Cover · Editorial surface — iOS `EditorialCoverComposition`
 * （ios/BooksAndVocab/Views/Vocabulary/Components/NotebookCard.swift）的 web 鏡像。
 *
 * scene 樹（EditorialCoverScene）：
 *   ZStack[ RoundedRect(coverColor.opacity(0.35)) → EditorialCoverComposition ]
 *     .frame(grid 168×224 / hero 320×200)
 *     .clipShape(RoundedRectangle(AppRadius.lg=12, .continuous))
 *     .padding(AppSpacing.s4=16)
 *
 * EditorialCoverComposition：ZStack(.topLeading)[
 *   - (grid && active) D3 spine：Rectangle(darken(cover,0.4)) width 3pt，貼左緣
 *   - Name + rule：VStack(.leading, spacing s2=8){
 *       Text(name).serif(grid 22 / hero 32, bold).primaryText.lineLimit(2).tail
 *       Rectangle(darken(cover,0.3)).frame(width geo.width*0.25, height dividerStandard=1)
 *     }.padding(outerPadding: grid s2=8 / hero s3=12)
 *   - (cardCount>0) N 詞 bottom-trailing：Text("\(n) 詞").monoLabel(mono 10 bold)
 *       .secondaryText.padding(outerPadding)
 * ]
 *
 * 畫布透明（component-isolated，corner srgba 0,0,0,0）：crop = scene 自身
 * （cover frame + s4 padding 的 intrinsic box）。
 */
export function NotebookCoverEditorialScreen({
  scenario,
}: {
  scenario: ScenarioId<'notebook-cover-editorial'>
}) {
  const item = NOTEBOOK_COVER_EDITORIAL_FIXTURES[scenario]
  return (
    <div className="nce-component-surface">
      <EditorialCover item={item} />
    </div>
  )
}

function EditorialCover({ item }: { item: EditorialCoverItem }) {
  const rgba35 = withAlpha(item.coverColor, 0.35)
  const ruleColor = darken(item.coverColor, 0.3)
  const spineColor = darken(item.coverColor, 0.4)
  return (
    <div className={`nce-cover nce-cover--${item.style}`}>
      {/* RoundedRect(coverColor.opacity(0.35)) 底 */}
      <div className="nce-cover-fill" style={{ background: rgba35 }} />

      {/* D3 spine — grid only & active */}
      {item.style === 'grid' && item.isActive ? (
        <div className="nce-spine" style={{ background: spineColor }} />
      ) : null}

      {/* Name + rule（top-leading）— GeometryReader 內 VStack(.leading, s2) */}
      <div className="nce-namebox">
        <span className="nce-name">{item.name}</span>
        {/* rule width = geo.width*0.25 = cover 內容寬*0.25（含 outerPadding 後的 geo），
            height = dividerStandard = 1pt */}
        <div className="nce-rule" style={{ background: ruleColor }} />
      </div>

      {/* N 詞 bottom-trailing（cardCount>0） */}
      {item.cardCount > 0 ? (
        <div className="nce-countbox">
          <span className="nce-count">{item.cardCount} 詞</span>
        </div>
      ) : null}
    </div>
  )
}

// ── 顏色工具 ──────────────────────────────────────────────
// iOS Color.opacity(0.35) over transparent → straight-alpha rgba。
function withAlpha(hex: string, a: number): string {
  const { r, g, b } = parseHex(hex)
  return `rgba(${r}, ${g}, ${b}, ${a})`
}

// NotebookPalette.darken：HSB brightness ×(1-amount)，hue/sat 保持。
function darken(hex: string, amount: number): string {
  const { r, g, b } = parseHex(hex)
  const [h, s, v] = rgbToHsb(r, g, b)
  const [nr, ng, nb] = hsbToRgb(h, s, v * (1 - amount))
  return `rgb(${nr}, ${ng}, ${nb})`
}

function parseHex(hex: string): { r: number; g: number; b: number } {
  const n = parseInt(hex.slice(1), 16)
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 }
}

function rgbToHsb(r: number, g: number, b: number): [number, number, number] {
  const rn = r / 255
  const gn = g / 255
  const bn = b / 255
  const max = Math.max(rn, gn, bn)
  const min = Math.min(rn, gn, bn)
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

function hsbToRgb(h: number, s: number, v: number): [number, number, number] {
  const c = v * s
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1))
  const m = v - c
  let r = 0
  let g = 0
  let b = 0
  if (h < 60) [r, g, b] = [c, x, 0]
  else if (h < 120) [r, g, b] = [x, c, 0]
  else if (h < 180) [r, g, b] = [0, c, x]
  else if (h < 240) [r, g, b] = [0, x, c]
  else if (h < 300) [r, g, b] = [x, 0, c]
  else [r, g, b] = [c, 0, x]
  return [
    Math.round((r + m) * 255),
    Math.round((g + m) * 255),
    Math.round((b + m) * 255),
  ]
}
