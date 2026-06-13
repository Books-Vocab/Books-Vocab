import { useEffect, useRef, useState } from 'react'
import type { CSSProperties, PointerEvent as ReactPointerEvent } from 'react'
import { motion } from 'framer-motion'
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
import { useNotebookStore, type NotebookSheet } from './store'
import { useNotebookApiStore } from './useNotebookApiStore'
import { VocabSceneShell } from '../../shared/VocabSceneShell'
import { useShellNav } from '../../shell/ShellNavContext'
import { screenFor } from '../../shell/nav'
import { Sheet, snappy, usePreferredTransition } from '../../motion'
import './notebook.css'

/**
 * Long-press → secondary affordance（觸控裝置開卡片選單）。foundation 的 useSwipeBack
 * 只管 edge-back，無 long-press primitive，故此處在 surface 內薄包一個 pointer 計時器
 * （非 spring physics，不違反「勿手刻轉場」）。pointermove 超過 slop 視為捲動意圖 →
 * 取消，避免與列表捲動衝突。
 */
function useLongPress(onLongPress: () => void, ms = 450, slop = 10) {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const origin = useRef<{ x: number; y: number } | null>(null)
  const clear = () => {
    if (timer.current !== null) {
      clearTimeout(timer.current)
      timer.current = null
    }
    origin.current = null
  }
  useEffect(() => clear, [])
  return {
    onPointerDown: (e: ReactPointerEvent) => {
      if (e.pointerType === 'mouse') return // 滑鼠用 right-click，不走 long-press
      origin.current = { x: e.clientX, y: e.clientY }
      timer.current = setTimeout(() => {
        onLongPress()
        clear()
      }, ms)
    },
    onPointerMove: (e: ReactPointerEvent) => {
      if (!origin.current) return
      const dx = Math.abs(e.clientX - origin.current.x)
      const dy = Math.abs(e.clientY - origin.current.y)
      if (dx > slop || dy > slop) clear()
    },
    onPointerUp: clear,
    onPointerCancel: clear,
  }
}

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
 *
 * 當 URL 含 shell=1 時，切換至 API-backed useNotebookApiStore（真實後端資料 +
 * 樂觀更新 + rollback）。非 ready 態由 VocabSceneShell 包裹。
 */

function NotebookCard({
  card,
  onOpen,
  onMore,
}: {
  card: NotebookFixtureCard
  /** 主要動作：單擊卡片本體 → 打開該單字本（dispatch open-notebook nav 邊）。 */
  onOpen: () => void
  /** 次要動作：overflow 鈕 / 右鍵 / 長按 → 開改名/刪除選單。 */
  onMore: () => void
}) {
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
  // 卡片按壓手感：whileTap 縮放，transition 走 foundation 的 snappy spring；
  // prefers-reduced-motion 時 usePreferredTransition 收斂為 instant。靜止 scale=1
  // 無 transform → parity 首屏 DOM/像素不變。
  const pressTransition = usePreferredTransition(snappy)
  const longPress = useLongPress(onMore)
  return (
    <motion.div
      className="nb-card"
      style={coverVars}
      data-name={card.name}
      whileTap={{ scale: 0.97 }}
      transition={pressTransition}
    >
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

      {/* 主要動作 — 透明 overlay 鈕蓋整卡，單擊打開該單字本（鏡射 iOS NotebookCard
          tap → notebook 詞庫）。無視覺 chrome → pixel-neutral，capture 首屏不變。
          右鍵 / 長按 → 次要選單（onMore）。 */}
      <button
        type="button"
        className="nb-card-open"
        aria-label={`打開 ${card.name}`}
        data-name={card.name}
        onClick={onOpen}
        onContextMenu={(e) => {
          e.preventDefault()
          onMore()
        }}
        {...longPress}
      />

      {/* 次要動作 — 右上角 overflow 鈕（改名/刪除選單）。stopPropagation 避免觸發
          底下的 open overlay。glyph 預設透明、hover/focus 才淡入 → 首屏 pixel-neutral。 */}
      <button
        type="button"
        className="nb-card-more"
        aria-label={`${card.name} 選單`}
        data-name={card.name}
        onClick={(e) => {
          e.stopPropagation()
          onMore()
        }}
      >
        <EllipsisIcon size={18} className="nb-card-more-glyph" />
      </button>
    </motion.div>
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
  // Escape 關閉（empirical bug：原選單不吃 Escape）。掛 document keydown，捕獲全域
  // Esc；卸載時移除。backdrop 點擊與 Esc 兩條乾淨退路。
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])
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

/** sheet 標題 / 送出按鈕文案（add / edit 兩態共用）。 */
function sheetCopy(mode: 'add' | 'edit') {
  return mode === 'add'
    ? { title: '新增單字本', submitLabel: '建立' }
    : { title: '重新命名', submitLabel: '儲存' }
}

/**
 * Sheet 內的表單本體（輸入 + 送出）— 由 parity 靜態殼與 shared Sheet 殼共用，
 * 確保兩條路 sheet 內容單一真相、不 drift。grabber / scrim 等 chrome 由各自外殼提供。
 */
function NotebookEditForm({
  mode,
  initialName,
  onSubmit,
  onClose,
  showClose,
}: {
  mode: 'add' | 'edit'
  initialName: string
  onSubmit: (name: string) => void
  onClose: () => void
  /** parity 靜態殼自帶 xmark close 鈕；shared Sheet 靠 grabber/backdrop/Esc 關閉。 */
  showClose: boolean
}) {
  const [name, setName] = useState(initialName)
  const { title, submitLabel } = sheetCopy(mode)
  const canSubmit = name.trim().length > 0
  return (
    <>
      <div className="nb-sheet-head">
        <p className="nb-sheet-title">{title}</p>
        {showClose && (
          <button type="button" className="nb-sheet-close" aria-label="關閉" onClick={onClose}>
            <XmarkIcon size={16} />
          </button>
        )}
      </div>
      {/* CloudKit 同步為 web stub（誠實邊界）：只動 in-memory 列表，不上雲。 */}
      <input
        className="nb-sheet-input"
        type="text"
        placeholder="單字本名稱"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && canSubmit) onSubmit(name)
        }}
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
    </>
  )
}

/**
 * Parity / fixture 路徑的底部 sheet — 沿用既有靜態 scrim + grabber 標記，capture
 * 行為與首屏逐位元不變（vaul 會 portal 到 document.body、跳出 phone-frame，故不在
 * parity 路徑掛 shared Sheet）。
 */
function NotebookEditSheetStatic({
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
  const { title } = sheetCopy(mode)
  return (
    <div className="nb-sheet-scrim" role="dialog" aria-modal="true" aria-label={title} onClick={onClose}>
      <div className="nb-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="nb-sheet-grabber" />
        <NotebookEditForm
          mode={mode}
          initialName={initialName}
          onSubmit={onSubmit}
          onClose={onClose}
          showClose
        />
      </div>
    </div>
  )
}

/**
 * Shell 路徑的底部 sheet — 走 foundation 的 shared Sheet（vaul），原生 drag-to-dismiss
 * + backdrop + Esc + focus trap，grabber 由 Sheet 提供，故表單不再自帶 close 鈕。
 */
function NotebookEditSheetShared({
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
  const { title } = sheetCopy(mode)
  return (
    <Sheet open onClose={onClose} ariaLabel={title}>
      <div className="nb-sheet-shared">
        <NotebookEditForm
          mode={mode}
          initialName={initialName}
          onSubmit={onSubmit}
          onClose={onClose}
          showClose={false}
        />
      </div>
    </Sheet>
  )
}

export function NotebookScreen({ scenario }: { scenario: ScenarioId<'notebook'> }) {
  const shell = new URLSearchParams(window.location.search).get('shell') === '1'
  if (shell) {
    return <NotebookScreenApi />
  }
  return <NotebookScreenFixture scenario={scenario} />
}

/** Fixture-driven screen — parity harness 路徑（無 shell=1 時）。 */
function NotebookScreenFixture({ scenario }: { scenario: ScenarioId<'notebook'> }) {
  const fixture = NOTEBOOK_FIXTURES[scenario]
  const store = useNotebookStore(fixture)
  return <NotebookBody cards={store.cards} store={store} reviewTotal={fixture.reviewTotal} />
}

/** API-driven screen — shell=1 時使用真實後端資料。 */
function NotebookScreenApi() {
  const store = useNotebookApiStore()
  const nav = useShellNav()
  const reviewTotal = store.cards.reduce((sum, c) => sum + c.actionableCount, 0)
  // 主要動作：單擊卡片 → 導航至該本單字本詞庫（誠實導航圖 notebook→vocabulary 邊，
  // 攜 notebookId）。parity 路徑（無 shell）不傳此 callback → onOpen no-op，首屏不變。
  const onOpenNotebook = (card: NotebookFixtureCard) => {
    store.closeMenu()
    nav.navigate(screenFor('vocabulary', { notebookId: card.id }))
  }
  // 次要動作的「編輯」→ 導航至 notebook-edit surface（誠實導航圖既有的 notebook→
  // notebook-edit 邊）。先關 more 選單，再 push。
  const onEditNotebook = () => {
    store.closeMenu()
    nav.navigate(screenFor('notebook-edit'))
  }
  return (
    <VocabSceneShell
      status={store.status === 'ready' ? 'content' : store.status === 'loading' ? 'loading' : 'error'}
      onRetry={store.retry}
    >
      <NotebookBody
        cards={store.cards}
        store={store}
        reviewTotal={reviewTotal}
        onOpenNotebook={onOpenNotebook}
        onEditNotebook={onEditNotebook}
        useSharedSheet
      />
    </VocabSceneShell>
  )
}

/** 共享的 notebook 畫面本體（fixture / API 兩條路共用）。 */
function NotebookBody({
  cards,
  store,
  reviewTotal,
  onOpenNotebook,
  onEditNotebook,
  useSharedSheet = false,
}: {
  cards: NotebookFixtureCard[]
  store: {
    sheet: NotebookSheet | null
    menuCardName: string | null
    showFilter: boolean
    openAdd: () => void
    openEditFor: (cardName: string) => void
    closeSheet: () => void
    openMenu: (cardName: string) => void
    closeMenu: () => void
    addNotebook: (name: string) => void | Promise<void>
    renameNotebook: (oldName: string, newName: string) => void | Promise<void>
    deleteNotebook: (cardName: string) => void | Promise<void>
  }
  reviewTotal: number
  /** shell 路徑：單擊卡片導航至該本單字本詞庫（notebook→vocabulary 邊，攜 notebookId）。
      省略（parity/fixture 路徑）→ onOpen no-op，capture DOM 與行為不變。 */
  onOpenNotebook?: (card: NotebookFixtureCard) => void
  /** shell 路徑：點「編輯」導航至 notebook-edit surface（誠實導航圖既有邊）。
      省略（parity/fixture 路徑）→ 沿用原地改名 sheet，capture DOM 不變。 */
  onEditNotebook?: (cardName: string) => void
  /** shell 路徑：新增/編輯走 foundation shared Sheet（vaul，drag-dismiss）。
      省略（parity/fixture 路徑）→ 用靜態 scrim sheet，capture 首屏不變。 */
  useSharedSheet?: boolean
}) {
  // 編輯 sheet 鎖定的卡（以名稱定位）；改名時回填初值。
  const editingName = store.sheet?.kind === 'edit' ? store.sheet.cardName : null
  const editingCard =
    editingName !== null ? cards.find((c) => c.name === editingName) ?? null : null

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
            <span className="nb-pill-num">{reviewTotal}</span>
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
          {cards.map((card) => (
            <NotebookCard
              key={card.name}
              card={card}
              onOpen={() => onOpenNotebook?.(card)}
              onMore={() => store.openMenu(card.name)}
            />
          ))}
        </div>
      </div>

      {/* ── 浮層（互動後才掛載，首屏無此 DOM）── */}
      {store.menuCardName !== null && (
        <NotebookCardMenu
          cardName={store.menuCardName}
          onEdit={() =>
            onEditNotebook
              ? onEditNotebook(store.menuCardName!)
              : store.openEditFor(store.menuCardName!)
          }
          onDelete={() => store.deleteNotebook(store.menuCardName!)}
          onClose={store.closeMenu}
        />
      )}
      {store.sheet?.kind === 'add' &&
        (useSharedSheet ? (
          <NotebookEditSheetShared
            mode="add"
            initialName=""
            onSubmit={store.addNotebook}
            onClose={store.closeSheet}
          />
        ) : (
          <NotebookEditSheetStatic
            mode="add"
            initialName=""
            onSubmit={store.addNotebook}
            onClose={store.closeSheet}
          />
        ))}
      {editingCard &&
        (useSharedSheet ? (
          <NotebookEditSheetShared
            mode="edit"
            initialName={editingCard.name}
            onSubmit={(name) => store.renameNotebook(editingCard.name, name)}
            onClose={store.closeSheet}
          />
        ) : (
          <NotebookEditSheetStatic
            mode="edit"
            initialName={editingCard.name}
            onSubmit={(name) => store.renameNotebook(editingCard.name, name)}
            onClose={store.closeSheet}
          />
        ))}
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
