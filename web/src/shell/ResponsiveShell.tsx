import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import type { ComponentType, SVGProps } from 'react'
import type { Appearance, HarnessConfig } from '../harness/scenarios'
import { PhoneFrame } from '../harness/PhoneFrame'
import { ChevronLeftIcon, GearIcon, PersonIcon, SyncCircleIcon } from './icons'
import { renderScreen } from './screenRegistry'
import {
  currentScreen,
  initialNavState,
  isLiveReaderScreen,
  pop,
  push,
  screenFor,
  selectTab,
  type NavState,
  type Screen,
} from './nav'
import { ShellNavProvider, type ShellNav } from './ShellNavContext'
import { SHELL_TABS, type TabSpec } from './tabs'
import '../styles/responsive.css'

// Live Reader（epub.js 真渲染）— dynamic import，epub.js 不進 parity bundle（與
// AppShell 同一條 lazy 路徑）。桌面/平板殼層內點書（open-book push → reader screen
// 在書庫 tab 深 >1）才掛載真閱讀器，填滿內容窗格；靜態 parity ReaderScreen 僅供
// ?surface=reader（無殼層）對拍路徑，零改動。
const LiveReaderScreen = lazy(() =>
  import('../surfaces/reader-live/LiveReaderScreen').then((m) => ({
    default: m.LiveReaderScreen,
  })),
)

/**
 * ResponsiveShell — the single web app shell container for tablet/desktop, and
 * the mobile breakpoint delegator.
 *
 * PARITY ISOLATION (do not break):
 *   - This component is only mounted on the shell path (App.tsx shell===true).
 *     The parity capture path (?surface=X without ?shell=1) renders
 *     PhoneFrame -> SurfaceView and never reaches here.
 *   - All responsive CSS lives under .kg-responsive-shell (responsive.css),
 *     which this is the only component to mount. Nothing here can touch the
 *     .phone-frame parity DOM.
 *
 * Behaviour by breakpoint (literal px mirror responsive.css):
 *   - mobile  (< 768): delegate to the EXISTING AppShell verbatim by rendering
 *     <PhoneFrame config shell /> — same PhoneFrame wrapping + hotzone overlay
 *     as today's ?shell=1 path. Zero behavioural change on mobile.
 *   - tablet  (768-1119): persistent 72px icon rail (SHELL_TABS) + single fluid
 *     content pane. Deep push = same-column stack (slide-over) via the nav stack.
 *   - desktop (>= 1120): persistent 280px side nav (expanded labels) + master
 *     pane + detail pane. [root] -> master only; [root, detail] -> master +
 *     detail side by side; deeper -> detail-pane internal stack with back.
 *
 * Surfaces are rendered via the shared screenRegistry into the panes; surface
 * files are NOT edited here (surface-internal responsive is a later fan-out).
 * The nav.ts reducer + ShellNavContext are REUSED (not forked) so the mobile
 * AppShell and this desktop shell share one navigation model + one route table.
 */

type Breakpoint = 'mobile' | 'tablet' | 'desktop' | 'wide'

/** Literal breakpoint edges — must match the @media queries in responsive.css. */
function breakpointFor(width: number): Breakpoint {
  if (width < 768) return 'mobile'
  if (width < 1120) return 'tablet'
  if (width < 1440) return 'desktop'
  return 'wide'
}

/** Track the viewport breakpoint via window width + resize listener. */
function useBreakpoint(): Breakpoint {
  const [bp, setBp] = useState<Breakpoint>(() =>
    typeof window === 'undefined' ? 'desktop' : breakpointFor(window.innerWidth),
  )
  useEffect(() => {
    if (typeof window === 'undefined') return
    const onResize = () => setBp(breakpointFor(window.innerWidth))
    onResize()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  return bp
}

type NavGlyph = ComponentType<SVGProps<SVGSVGElement> & { size?: number; strokeWidth?: number }>

/** Secondary nav section (設定 / 同步 / 帳號) — deep targets in the settings tree. */
type SecondaryNavItem = { id: string; label: string; icon: NavGlyph; target: Screen }

const SECONDARY_NAV: readonly SecondaryNavItem[] = [
  { id: 'settings', label: '設定', icon: GearIcon, target: screenFor('settings') },
  { id: 'sync', label: '同步', icon: SyncCircleIcon, target: screenFor('sync') },
  { id: 'account', label: '帳號', icon: PersonIcon, target: screenFor('settings-account-detail') },
]

function NavItem({
  icon: Icon,
  label,
  selected,
  disabled,
  onSelect,
}: {
  icon: NavGlyph
  label: string
  selected: boolean
  disabled: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      className="shell-nav-item"
      data-selected={selected}
      data-disabled={disabled}
      aria-pressed={selected}
      aria-disabled={disabled}
      disabled={disabled}
      onClick={onSelect}
    >
      <span className="shell-nav-item-icon">
        <Icon size={24} />
      </span>
      <span className="shell-nav-item-label">{label}</span>
    </button>
  )
}

/** A surface rendered into a pane (shared screenRegistry route table). */
function PaneSurface({ screen }: { screen: Screen }) {
  return <div className="shell-pane-surface">{renderScreen(screen)}</div>
}

export function ResponsiveShell({ config }: { config: HarnessConfig }) {
  const breakpoint = useBreakpoint()
  const appearance: Appearance = config.appearance

  const [nav, setNav] = useState<NavState>(() =>
    initialNavState(config.surface, config.scenario as string),
  )

  const activeTab = SHELL_TABS.find((t) => t.id === nav.tabId) ?? SHELL_TABS[0]
  const stack = nav.stacks[nav.tabId] ?? []
  const screen = currentScreen(nav)

  // Shared shell-nav context: surface row/card clicks push onto the active tab
  // stack (attaching real entity ids); current screen params flow to surfaces.
  const shellNav = useMemo<ShellNav>(
    () => ({
      navigate: (target: Screen) => setNav((s) => push(s, target)),
      params: screen?.params ?? {},
    }),
    [screen],
  )

  // mobile: delegate to the EXISTING AppShell verbatim (via PhoneFrame shell=1).
  // Same PhoneFrame wrapping + hotzone overlay + nav stack behaviour as today.
  if (breakpoint === 'mobile') {
    return (
      <div className="kg-responsive-shell" data-breakpoint="mobile" data-appearance={appearance}>
        <PhoneFrame config={config} shell />
      </div>
    )
  }

  // tablet/desktop: own chrome (rail or side nav) + panes rendered via registry.
  const isSurfaceTab = activeTab.kind === 'surface'
  // master = root screen of the active tab; detail = next stack entry (depth >= 2).
  const masterScreen = isSurfaceTab ? (stack[0] ?? null) : null
  const detailStack = stack.slice(1)
  const detailScreen = detailStack[detailStack.length - 1] ?? null
  const hasDetail = detailStack.length >= 1
  const detailHasBack = detailStack.length >= 2

  // 點書開啟的 reader 畫面（書庫 tab push 後 depth>1）→ 掛 Live Reader 真閱讀器
  // （epub.js），取代靜態 parity ReaderScreen。Live Reader 自帶「書庫」返回鈕 +
  // chrome，故填滿整個內容區（不切 master/detail 雙窗格），onBack 退一層回書架。
  // bookId 由 currentScreen（深層 reader screen）的 params 經 ShellNavContext 流到
  // useLiveReaderApi。掛在 .shell-pane-surface 內 → 觸發 live-reader.css 的容器查詢
  // （居中 var(--reader-measure) 欄 + 寬窗格持久 TOC + epub.js ResizeObserver 重排）。
  // 謂詞與 mobile AppShell 共用 nav.isLiveReaderScreen（單一真相，避免雙殼 drift）。
  const isLiveReader = isLiveReaderScreen(nav)

  function selectPrimary(tab: TabSpec) {
    if (tab.kind !== 'surface') return
    setNav((s) => selectTab(s, tab.id))
  }

  function selectSecondary(target: Screen) {
    // Push the settings-subtree target onto the active tab's stack so it fills
    // the detail pane (desktop) / slides over (tablet) — reusing the nav stack.
    setNav((s) => push(s, target))
  }

  return (
    <div
      className="kg-responsive-shell"
      data-breakpoint={breakpoint}
      data-appearance={appearance}
      data-tab={nav.tabId}
    >
      <nav className="shell-chrome" aria-label="主導航">
        <div className="shell-chrome-primary">
          {SHELL_TABS.map((tab) => (
            <NavItem
              key={tab.id}
              icon={tab.icon}
              label={tab.label}
              selected={tab.id === nav.tabId}
              disabled={tab.kind === 'placeholder'}
              onSelect={() => selectPrimary(tab)}
            />
          ))}
        </div>
        <div className="shell-chrome-secondary">
          {SECONDARY_NAV.map((item) => (
            <NavItem
              key={item.id}
              icon={item.icon}
              label={item.label}
              selected={detailScreen?.surface === item.target.surface}
              disabled={false}
              onSelect={() => selectSecondary(item.target)}
            />
          ))}
        </div>
      </nav>

      <div className="shell-panes" data-has-detail={isLiveReader ? false : hasDetail}>
        <ShellNavProvider value={shellNav}>
          {isLiveReader ? (
            // Live Reader 填滿內容區（單一窗格，無 master/detail 切分）。掛在
            // .shell-pane-surface 內以啟用 live-reader.css 容器查詢（居中閱讀欄 +
            // 持久 TOC + epub.js ResizeObserver 重排到新欄寬）。
            <div className="shell-pane-master shell-pane-reader">
              <div className="shell-pane-surface">
                <Suspense fallback={null}>
                  <LiveReaderScreen onBack={() => setNav((s) => pop(s))} />
                </Suspense>
              </div>
            </div>
          ) : breakpoint === 'tablet' ? (
            // Single fluid content pane: show the deepest screen (slide-over),
            // else the master. Deep push stacks in the same column. This is the
            // .shell-pane-master class on purpose — tablet has no side-by-side
            // detail pane, and the tablet @media in responsive.css hides
            // .shell-pane-detail (the desktop deep-push column).
            <div className="shell-pane-master">
              {screen ? <PaneSurface screen={screen} /> : null}
            </div>
          ) : (
            <>
              <div className="shell-pane-master">
                {masterScreen ? <PaneSurface screen={masterScreen} /> : null}
              </div>
              {hasDetail && (
                <div className="shell-pane-detail">
                  {detailHasBack && (
                    <button
                      type="button"
                      className="shell-pane-back"
                      aria-label="返回"
                      onClick={() => setNav((s) => pop(s))}
                    >
                      <ChevronLeftIcon size={18} />
                      返回
                    </button>
                  )}
                  {detailScreen ? <PaneSurface screen={detailScreen} /> : null}
                </div>
              )}
            </>
          )}
        </ShellNavProvider>
      </div>
    </div>
  )
}
