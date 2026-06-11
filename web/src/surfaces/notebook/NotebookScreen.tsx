import { useState } from 'react'
import type { CSSProperties } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import { NOTEBOOK_FIXTURES } from './fixtures'
import type { NotebookFixtureCard } from './fixtures'
import {
  EllipsisIcon,
  FilterCircleIcon,
  PencilIcon,
  PlusIcon,
  SparklesIcon,
  TrashIcon,
  XmarkIcon,
} from './icons'
import { useNotebookStore } from './store'
import './notebook.css'

/**
 * Notebook surface — iOS NotebookListView/NotebookListContent 的 web 重寫。
 * 幾何常數逐一對齊 iOS（見 notebook.css 的 px 註解）；結構順序 =
 * NotebookListView.body：large nav title → NotebookReviewActionBar（今日複習 +
 * CTA/filter/plus pill）→ AppAirDivider → LazyVStack book-row（NotebookCard）。
 *
 * 互動化（fixtures 當資料層，store 薄狀態）：新增 pill 開底部 sheet 真輸入建本；
 * 卡片 more 選單（透明 overlay 鈕，pixel-neutral）→ 編輯（改名 sheet）/ 刪除（即時
 * 移除）。誠實邊界：web 無 SwiftData/CloudKit，操作只動 in-memory 列表、不持久化、
 * 不同步後端（iOS NotebookListCoordinator 的 server PUT/getUserConfig 在 web 為 no-op）。
 * parity 契約：初值 cards = fixture.cards、無浮層 → capture 首屏與靜態版逐位元相同。
 */

function NotebookCard({ card, onMore }: { card: NotebookFixtureCard; onMore: () => void }) {
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
    <div className="nb-card" style={coverVars} data-name={card.name}>
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

      {/* more 選單觸發 — 透明 overlay 鈕，蓋整卡（鏡射 iOS NotebookCard context menu
          的 long-press）。無視覺 chrome → pixel-neutral，capture 首屏不變。 */}
      <button
        type="button"
        className="nb-card-more"
        aria-label={`${card.name} 選單`}
        data-name={card.name}
        onClick={onMore}
      >
        <EllipsisIcon size={18} className="nb-card-more-glyph" />
      </button>
    </div>
  )
}

/** 卡片 more 選單浮層（編輯 / 刪除）。鏡射 iOS NotebookCard contextMenu。 */
function NotebookCardMenu({
  cardName,
  onEdit,
  onDelete,
  onClose,
}: {
  cardName: string
  onEdit: () => void
  onDelete: () => void
  onClose: () => void
}) {
  return (
    <div className="nb-menu-scrim" role="dialog" aria-modal="true" aria-label={`${cardName} 選單`} onClick={onClose}>
      <div className="nb-menu" onClick={(e) => e.stopPropagation()}>
        <p className="nb-menu-title">{cardName}</p>
        <button type="button" className="nb-menu-item" onClick={onEdit}>
          <PencilIcon size={17} />
          <span>編輯</span>
        </button>
        <button type="button" className="nb-menu-item nb-menu-item-destructive" onClick={onDelete}>
          <TrashIcon size={17} />
          <span>刪除</span>
        </button>
      </div>
    </div>
  )
}

/** 新增 / 編輯 notebook 的底部 sheet（真輸入框）。鏡射 iOS NotebookEditSheet。 */
function NotebookEditSheet({
  mode,
  initialName,
  onSubmit,
  onClose,
}: {
  mode: 'add' | 'edit'
  initialName: string
  onSubmit: (name: string) => void
  onClose: () => void
}) {
  const [name, setName] = useState(initialName)
  const title = mode === 'add' ? '新增單字本' : '重新命名'
  const submitLabel = mode === 'add' ? '建立' : '儲存'
  const canSubmit = name.trim().length > 0
  return (
    <div className="nb-sheet-scrim" role="dialog" aria-modal="true" aria-label={title} onClick={onClose}>
      <div className="nb-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="nb-sheet-grabber" />
        <div className="nb-sheet-head">
          <p className="nb-sheet-title">{title}</p>
          <button type="button" className="nb-sheet-close" aria-label="關閉" onClick={onClose}>
            <XmarkIcon size={16} />
          </button>
        </div>
        {/* CloudKit 同步為 web stub（誠實邊界）：只動 in-memory 列表，不上雲。 */}
        <input
          className="nb-sheet-input"
          type="text"
          placeholder="單字本名稱"
          value={name}
          onChange={(e) => setName(e.target.value)}
          aria-label="單字本名稱"
          autoFocus
        />
        <button
          type="button"
          className="nb-sheet-submit"
          disabled={!canSubmit}
          onClick={() => onSubmit(name)}
        >
          {submitLabel}
        </button>
      </div>
    </div>
  )
}

export function NotebookScreen({ scenario }: { scenario: ScenarioId<'notebook'> }) {
  const fixture = NOTEBOOK_FIXTURES[scenario]
  const store = useNotebookStore(fixture)

  // 編輯 sheet 鎖定的卡（以名稱定位）；改名時回填初值。
  const editingName = store.sheet?.kind === 'edit' ? store.sheet.cardName : null
  const editingCard =
    editingName !== null ? store.cards.find((c) => c.name === editingName) ?? null : null

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
          {store.showFilter && (
            <span className="nb-pill nb-pill-tool">
              <FilterCircleIcon size={15} />
            </span>
          )}
          {/* 新增 pill — <button> UA chrome 歸零，幾何沿用 .nb-pill（pixel-neutral）。 */}
          <button
            type="button"
            className="nb-pill nb-pill-tool nb-pill-button"
            aria-label="新增單字本"
            onClick={store.openAdd}
          >
            <PlusIcon size={15} />
          </button>
        </div>

        {/* AppAirDivider — hairline + dividerAir margin */}
        <div className="nb-air-divider" />

        <div className="nb-list">
          {store.cards.map((card) => (
            <NotebookCard key={card.name} card={card} onMore={() => store.openMenu(card.name)} />
          ))}
        </div>
      </div>

      {/* ── 浮層（互動後才掛載，首屏無此 DOM）── */}
      {store.menuCardName !== null && (
        <NotebookCardMenu
          cardName={store.menuCardName}
          onEdit={() => store.openEditFor(store.menuCardName!)}
          onDelete={() => store.deleteNotebook(store.menuCardName!)}
          onClose={store.closeMenu}
        />
      )}
      {store.sheet?.kind === 'add' && (
        <NotebookEditSheet
          mode="add"
          initialName=""
          onSubmit={store.addNotebook}
          onClose={store.closeSheet}
        />
      )}
      {editingCard && (
        <NotebookEditSheet
          mode="edit"
          initialName={editingCard.name}
          onSubmit={(name) => store.renameNotebook(editingCard.name, name)}
          onClose={store.closeSheet}
        />
      )}
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
