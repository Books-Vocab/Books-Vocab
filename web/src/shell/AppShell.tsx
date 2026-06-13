import { lazy, Suspense, useMemo, useState } from 'react'
import type { Appearance, HarnessConfig, SurfaceId } from '../harness/scenarios'
import { BookshelfScreen } from '../surfaces/bookshelf/BookshelfScreen'
import { NotebookScreen } from '../surfaces/notebook/NotebookScreen'
import { PodcastScreen } from '../surfaces/podcast/PodcastScreen'
import { ReaderScreen } from '../surfaces/reader/ReaderScreen'
import { SettingsScreen } from '../surfaces/settings/SettingsScreen'
import { TodayReviewScreen } from '../surfaces/today-review/TodayReviewScreen'
import { VocabularyScreen } from '../surfaces/vocabulary/VocabularyScreen'
import { OverviewScreen } from '../surfaces/overview/OverviewScreen'
import { useNotebookApiStore } from '../surfaces/notebook/useNotebookApiStore'
import { useBookshelfApiStore } from '../surfaces/bookshelf/useBookshelfApiStore'
import { ChevronLeftIcon } from './icons'
import {
  currentScreen,
  initialNavState,
  pop,
  push,
  pushTargetFor,
  selectTab,
  stackDepth,
  type NavIntent,
  type NavState,
  type Screen,
  type ScreenParams,
} from './nav'
import { ShellNavProvider, type ShellNav } from './ShellNavContext'
import { SHELL_TABS, type TabSpec } from './tabs'
import './shell.css'

// Live Reader（epub.js 真渲染）— dynamic import，epub.js 不進 parity bundle。
// 殼層內點書（open-book push → reader screen 在書庫 tab 深 >1）才掛載真閱讀器，
// 取代靜態 parity reader chrome；既有 ?surface=reader 對拍路徑零改動。
const LiveReaderScreen = lazy(() =>
  import('../surfaces/reader-live/LiveReaderScreen').then((m) => ({
    default: m.LiveReaderScreen,
  })),
)

/**
 * Web app 殼層 — 像素對齊 iOS TabView（ContentView.swift）的底部 tab bar，並把
 * 各自孤島的 web surface 接成可達的 app 導航。
 *
 * 導航模型在 `nav.ts`（純函式 reducer + 誠實導航圖）：每個 surface-tab 各擁有一條
 * push/pop stack，切 tab 保留各自 stack（鏡射 iOS 各 section 自有 NavigationStack）。
 * 點擊熱區（書卡 / 單字本卡 / 今日複習 CTA）push 下一層；stack 深 >1 時左上角出
 * back chevron 退一層。
 *
 * Surface 本體不改：點擊熱區是疊在 surface 之上的透明 overlay 按鈕（殼層層、不碰
 * surface DOM），故所有 surface 維持 pixel-neutral，parity capture 完全不受影響。
 *
 * URL 契約：殼層由 PhoneFrame 在 ?shell=1 時掛載，預設不啟用——既有
 * ?surface=&scenario=&appearance= 行為完全不變。殼層初始 tab/scenario 對齊 URL
 * （見 nav.initialNavState）。
 */

function renderScreen(screen: Screen) {
  // discriminated union：switch 後 scenario 自動窄化為該 surface 合法 id。
  // 注：surface 在 shell 內讀「攜帶的實體 id」走 ShellNavContext.params（見
  // ShellNavProvider 注入），prop 優先於 window.location.search，後者為 deep-link
  // fallback。surface 公開 prop 簽章不變（仍只吃 scenario），故 parity 路徑零改動。
  switch (screen.surface) {
    case 'bookshelf':
      return <BookshelfScreen scenario={screen.scenario} />
    case 'notebook':
      return <NotebookScreen scenario={screen.scenario} />
    case 'settings':
      return <SettingsScreen scenario={screen.scenario} />
    case 'reader':
      return <ReaderScreen scenario={screen.scenario} />
    case 'vocabulary':
      return <VocabularyScreen scenario={screen.scenario} />
    case 'today-review':
      return <TodayReviewScreen scenario={screen.scenario} />
    case 'podcast':
      return <PodcastScreen scenario={screen.scenario} />
    case 'overview':
      return <OverviewScreen scenario={screen.scenario} />
    // selection-* 為元件級 scene，無 app 殼層入口（不會進 nav stack）。
    case 'selection-toolbar':
    case 'selection-tile':
      return null
  }
}

/**
 * 某 surface 在殼層內的可點擊熱區（誠實導航圖的 UI 投影）。每個熱區 = 一個透明
 * overlay 按鈕，疊在 surface 對應視覺區之上。surface 無對應熱區 → 空陣列。
 */
type HotZone = { intent: NavIntent; className: string; label: string }

function hotZonesFor(surface: SurfaceId): HotZone[] {
  switch (surface) {
    case 'bookshelf':
      // 整個書格區可點 → 開書（→ reader）。
      return [{ intent: 'open-book', className: 'shell-hot shell-hot-bookgrid', label: '開啟書籍' }]
    case 'notebook':
      // 今日複習 CTA（頂部）→ today-review；卡片列表區 → vocabulary。
      return [
        { intent: 'open-today-review', className: 'shell-hot shell-hot-nb-review', label: '今日複習' },
        { intent: 'open-notebook', className: 'shell-hot shell-hot-nb-cards', label: '開啟單字本' },
      ]
    default:
      return []
  }
}

function Placeholder({ label }: { label: string }) {
  return (
    <div className="shell-placeholder" role="status">
      <p className="shell-placeholder-title">{label}</p>
      <p className="shell-placeholder-note">尚未在 web 重寫</p>
    </div>
  )
}

function TabButton({
  tab,
  selected,
  onSelect,
}: {
  tab: TabSpec
  selected: boolean
  onSelect: () => void
}) {
  const Icon = tab.icon
  const disabled = tab.kind === 'placeholder'
  return (
    <button
      type="button"
      className="shell-tab"
      data-selected={selected}
      data-disabled={disabled}
      aria-pressed={selected}
      aria-disabled={disabled}
      disabled={disabled}
      onClick={onSelect}
    >
      <span className="shell-tab-icon">
        <Icon size={25} />
      </span>
      <span className="shell-tab-label">{tab.label}</span>
    </button>
  )
}

export function AppShell({ config }: { config: HarnessConfig }) {
  const [nav, setNav] = useState<NavState>(() =>
    initialNavState(config.surface, config.scenario as string),
  )
  const appearance: Appearance = config.appearance

  // 殼層讀實體列表以攜帶被點擊實體的真實 id（mock-backed，離線可用）。store
  // 公開狀態只暴露穩定鍵：notebook → card.name、book → book.title（rename/delete
  // 全程以此鍵定位），故深層導航以此為實體 id 鍵，由下游 surface 解析。
  const notebookStore = useNotebookApiStore()
  const bookshelfStore = useBookshelfApiStore()
  const firstNotebookId = notebookStore.cards[0]?.name
  const firstBookId = bookshelfStore.books[0]?.title

  const activeTab = SHELL_TABS.find((t) => t.id === nav.tabId) ?? SHELL_TABS[0]
  const screen = currentScreen(nav)
  const canGoBack = stackDepth(nav) > 1
  // 點書開啟的 reader 畫面（書庫 tab push 後 depth>1）→ 掛 Live Reader 真閱讀器，
  // 取代靜態 parity chrome。Live Reader 自帶「書庫」返回鈕 + chrome，故抑制殼層
  // overlay（back chevron + 熱區），避免雙層導航重疊。
  const isLiveReader = !!screen && screen.surface === 'reader' && canGoBack

  // navigate(target)：以當前 tab push 一層；surface 內部列/卡點擊可主動推進導航
  // （attach 真實實體 id 的 Screen）。當前畫面 params 一併經 context 暴露給 surface。
  const shellNav = useMemo<ShellNav>(
    () => ({
      navigate: (target: Screen) => setNav((s) => push(s, target)),
      params: screen?.params ?? {},
    }),
    [screen],
  )

  // 殼層既有熱區的實體 id 投影：點書庫整片 → 開首本書（帶 bookId）；點單字本卡片區
  // → 開首本單字本（帶 notebookId）。實體列表來自 API store（mock 離線可用）。
  function paramsForIntent(intent: NavIntent): ScreenParams | undefined {
    if (intent === 'open-book' && firstBookId !== undefined) return { bookId: firstBookId }
    if (intent === 'open-notebook' && firstNotebookId !== undefined)
      return { notebookId: firstNotebookId }
    return undefined
  }

  function handleHot(intent: NavIntent) {
    if (!screen) return
    const target = pushTargetFor(screen, intent, paramsForIntent(intent))
    if (target) setNav((s) => push(s, target))
  }

  return (
    <div className="app-shell" data-appearance={appearance} data-tab={nav.tabId}>
      <div className="shell-content">
        {activeTab.kind === 'surface' && screen ? (
          <div className="shell-screen" data-screen-surface={screen.surface}>
            <ShellNavProvider value={shellNav}>
            {isLiveReader ? (
              <Suspense fallback={null}>
                <LiveReaderScreen onBack={() => setNav((s) => pop(s))} />
              </Suspense>
            ) : (
              renderScreen(screen)
            )}
            {/* 透明 overlay 導航層：back chevron + 點擊熱區。不碰 surface DOM。
                Live Reader 自帶 chrome → 不疊殼層 overlay。 */}
            <div className="shell-nav-overlay" data-hidden={isLiveReader ? '' : undefined}>
              {canGoBack && !isLiveReader && (
                <button
                  type="button"
                  className="shell-back"
                  aria-label="返回"
                  onClick={() => setNav((s) => pop(s))}
                >
                  <ChevronLeftIcon size={20} />
                </button>
              )}
              {!isLiveReader && hotZonesFor(screen.surface).map((zone) => (
                <button
                  key={zone.intent}
                  type="button"
                  className={zone.className}
                  aria-label={zone.label}
                  onClick={() => handleHot(zone.intent)}
                />
              ))}
            </div>
            </ShellNavProvider>
          </div>
        ) : (
          <Placeholder label={activeTab.label} />
        )}
      </div>
      <nav className="shell-tab-bar" aria-label="主導航">
        {SHELL_TABS.map((tab) => (
          <TabButton
            key={tab.id}
            tab={tab}
            selected={tab.id === nav.tabId}
            onSelect={() => setNav((s) => selectTab(s, tab.id))}
          />
        ))}
      </nav>
    </div>
  )
}
