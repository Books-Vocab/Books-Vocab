import type { ScenarioId } from '../../harness/scenarios'
import { VOCAB_LINKED_CARD_FIXTURES } from './fixtures'
import { DocTextIcon, RectangleStackIcon, XmarkIcon } from './icons'
import { useVocabLinkedCardApiStore } from './useVocabLinkedCardApiStore'
import type { LinkedCardGroup } from './useVocabLinkedCardApiStore'
import './vocab-linked-card.css'

/**
 * LinkedCardOverlayStack surface — iOS `LinkedCardOverlayStack` 的 web 鏡像。
 *
 * 視圖樹（iOS）：
 *   ZStack {
 *     overlayScrim(black 0.20).ignoresSafeArea() ·
 *     ForEach(stack.enumerated()) { index, entry in linkedCardLayer(index) }
 *   }
 *
 * linkedCardLayer(index) = VStack(0)[
 *   VocabOverlayHeader(title index==0?"Linked Card":"Nested Link",
 *                      systemImage rectangle.stack, badge index>0?"+index":nil, close) ·
 *   Rectangle(divider, h dividerThin=0.5) ·
 *   WordDetailSheet(...)   // snapshot 下渲染 載入中 placeholder
 * ]
 * .frame(maxW max(420,680-index*18), maxH max(420,620-index*18))
 * .background(cardBackground).clipShape(RoundedRectangle(radii.overlay=8))
 * .overlay(stroke cardBorder.opacity(0.8), lw 1).appElevation(.z4)
 * .padding(.h s4=16 + index*10, .v s5=20 + index*8)
 * .scaleEffect(max(0.94, 1-index*0.02))
 * .offset(x index*8, y index*10)
 *
 * catalog scene layout=.fill：scrim over 透明畫布 → 卡片區 alpha 1、scrim 區 alpha 0.2
 * → alpha-mean≈0.74。故 transparent:true、phone-frame 透明、scrim 自繪 rgba(0,0,0,0.2)。
 *
 * snapshot 下 WordDetailSheet 顯 載入中 placeholder：VocabStateMessageCard(
 *   HStack[doc.text(iconSmall /accent) · "載入中"(body=sans15 semibold /primary) · Spacer] ·
 *   ProgressView(small)) padding h14 v12 radius8 border cardBorder.opacity(0.9)。
 */

const LAYER_OFFSET_X = 8 // AppOverlayMetrics.linkedCardLayerOffsetX
const LAYER_OFFSET_Y = 10 // AppOverlayMetrics.linkedCardLayerOffsetY
const SHRINK_STEP = 18 // AppOverlayMetrics.linkedCardLayerShrinkStep
const PAD_H = 16 // AppSpacing.s4
const PAD_V = 20 // AppSpacing.s5

function CardLayer({ index }: { index: number }) {
  const title = index === 0 ? 'Linked Card' : 'Nested Link'
  const badge = index > 0 ? `+${index}` : null
  const scale = Math.max(0.94, 1 - index * 0.02)

  // .frame(maxW/maxH) 在 393pt 視窗下被視窗+padding 夾住寬度；高度上限 620-index*18。
  const maxHeight = Math.max(420, 620 - index * SHRINK_STEP)
  const padH = PAD_H + index * LAYER_OFFSET_Y // 注意 iOS：.h 用 offsetY(10)、.v 用 offsetX(8)
  const padV = PAD_V + index * LAYER_OFFSET_X

  return (
    <div
      className="vlc-layer"
      style={{
        padding: `${padV}px ${padH}px`,
        transform: `translate(${index * LAYER_OFFSET_X}px, ${index * LAYER_OFFSET_Y}px) scale(${scale})`,
        zIndex: index + 1,
      }}
    >
      {/* iOS .frame(maxHeight:620-idx*18)：因 WordDetailSheet 內 ScrollView 撐滿，卡片實際=該高度（量測 ref 確認 620pt）。
          故給 height 而非 max-height，否則 flex column 只長到內容高（~120pt）造成 RMSE 災難。 */}
      <div className="vlc-card" style={{ height: `${maxHeight}px` }}>
        {/* VocabOverlayHeader */}
        <div className="vlc-header">
          <span className="vlc-header-label">
            <RectangleStackIcon className="vlc-header-icon" />
            {title}
          </span>
          {badge ? <span className="vlc-badge">{badge}</span> : null}
          <span className="vlc-spacer" />
          <button type="button" className="vlc-close" aria-label="關閉">
            <XmarkIcon className="vlc-close-glyph" />
          </button>
        </div>

        {/* Rectangle(divider, height dividerThin=0.5) */}
        <div className="vlc-divider" />

        {/* WordDetailSheet → 載入中 placeholder (VocabStateMessageCard) */}
        <div className="vlc-body">
          <div className="vlc-state-card">
            <div className="vlc-state-row">
              <DocTextIcon className="vlc-state-icon" />
              <span className="vlc-state-title">載入中</span>
            </div>
            <span className="vlc-spinner" aria-hidden="true">
              {Array.from({ length: 12 }).map((_, i) => (
                <i key={i} style={{ transform: `rotate(${i * 30}deg)` }} />
              ))}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

export function VocabLinkedCardScreen({
  scenario,
}: {
  scenario: ScenarioId<'vocab-linked-card'>
}) {
  const shell = new URLSearchParams(window.location.search).get('shell') === '1'
  if (shell) return <VocabLinkedCardApi />
  return <VocabLinkedCardFixture scenario={scenario} />
}

/** shell 路徑：以來源卡的 linksByKind 填入 overlay 卡內容。 */
function VocabLinkedCardApi() {
  const store = useVocabLinkedCardApiStore()
  return (
    <div className="vlc-surface">
      <div className="vlc-scrim" />
      <div className="vlc-layer" style={{ zIndex: 1 }}>
        <div className="vlc-card" style={{ height: '620px' }}>
          <div className="vlc-header">
            <span className="vlc-header-label">
              <RectangleStackIcon className="vlc-header-icon" />
              Linked Card
            </span>
            <span className="vlc-spacer" />
            <button type="button" className="vlc-close" aria-label="關閉">
              <XmarkIcon className="vlc-close-glyph" />
            </button>
          </div>
          <div className="vlc-divider" />
          <div className="vlc-body vlc-body--links">
            {store.status === 'ready' ? (
              store.groups.length === 0 ? (
                <p className="vlc-links-empty">尚無關聯卡片</p>
              ) : (
                store.groups.map((g) => <LinkGroup key={g.kind} group={g} />)
              )
            ) : (
              <LoadingState />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function LinkGroup({ group }: { group: LinkedCardGroup }) {
  return (
    <div className="vlc-link-group">
      <span className="vlc-link-label">{group.label}</span>
      {group.links.map((l) => (
        <div key={l.id} className="vlc-link-row">
          <span className="vlc-link-word">{l.word}</span>
          <span className="vlc-link-reason">{l.reason}</span>
        </div>
      ))}
    </div>
  )
}

function LoadingState() {
  return (
    <div className="vlc-state-card">
      <div className="vlc-state-row">
        <DocTextIcon className="vlc-state-icon" />
        <span className="vlc-state-title">載入中</span>
      </div>
      <span className="vlc-spinner" aria-hidden="true">
        {Array.from({ length: 12 }).map((_, i) => (
          <i key={i} style={{ transform: `rotate(${i * 30}deg)` }} />
        ))}
      </span>
    </div>
  )
}

/** Fixture-driven 疊層 placeholder（parity 路徑，DOM byte-identical）。 */
function VocabLinkedCardFixture({
  scenario,
}: {
  scenario: ScenarioId<'vocab-linked-card'>
}) {
  const fixture = VOCAB_LINKED_CARD_FIXTURES[scenario]
  const layers = Array.from({ length: fixture.depth }, (_, i) => i)

  return (
    <div className="vlc-surface">
      {/* overlayScrim(black 0.20).ignoresSafeArea() */}
      <div className="vlc-scrim" />
      {layers.map((index) => (
        <CardLayer key={index} index={index} />
      ))}
    </div>
  )
}
