import type { ScenarioId } from '../../harness/scenarios'
import { NOTEBOOK_COVER_FIXTURES, type CoverItem } from './fixtures'
import { CirclesOverlay, PatternOverlay } from './icons'
import './notebook-cover.css'

/**
 * NotebookCover surface — iOS `NotebookCoverView` 的 web 鏡像。
 *
 * 每張 cover：ZStack[ color 底 → (image | pattern overlay) → name text ]，
 * height 96，clipShape RoundedRectangle(12, continuous)。name = AppFonts.body
 * (17, semibold) 白字 + legibility shadow，lineLimit 2 + tail truncate +
 * minimumScaleFactor 0.85，置中，.padding(.h s2)。image-path fallback：路徑不存在
 * → loadImage 回 nil → 降級渲染 pattern（web 永遠無影像 → 等價 fallback）。
 *
 * scene = stage{ ScrollView{ content.padding(16) } }，畫布透明（component crop）。
 * grid = LazyVGrid(adaptive minimum 110, spacing 16)；rows = VStack(16) of
 * LazyVGrid(adaptive 110, spacing 12)。catalog 寬度 → 2 欄。
 */
export function NotebookCoverScreen({ scenario }: { scenario: ScenarioId<'notebook-cover'> }) {
  const scene = NOTEBOOK_COVER_FIXTURES[scenario]

  if (scene.layout === 'rows' && scene.rowSize) {
    const rows: CoverItem[][] = []
    for (let i = 0; i < scene.items.length; i += scene.rowSize) {
      rows.push(scene.items.slice(i, i + scene.rowSize))
    }
    return (
      <div className="nbc-component-surface">
        <div className="nbc-rows">
          {rows.map((row, ri) => (
            <div className="nbc-grid nbc-grid--tight" key={ri}>
              {row.map((item, i) => (
                <Cover key={i} item={item} />
              ))}
            </div>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="nbc-component-surface">
      <div className="nbc-grid">
        {scene.items.map((item, i) => (
          <Cover key={i} item={item} />
        ))}
      </div>
    </div>
  )
}

function Cover({ item }: { item: CoverItem }) {
  return (
    <div className="nbc-cover" style={{ background: item.color }}>
      {item.pattern === 'circles' ? (
        <CirclesOverlay />
      ) : item.pattern ? (
        <PatternOverlay pattern={item.pattern} />
      ) : null}
      {item.showsName ? <span className="nbc-cover-name">{item.name}</span> : null}
    </div>
  )
}
