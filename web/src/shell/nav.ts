import type { ScenarioId, SurfaceId } from '../harness/scenarios'
import { SURFACE_SCENARIOS } from '../harness/scenarios'
import { DEFAULT_TAB_ID, SHELL_TABS } from './tabs'

/**
 * 殼層導航模型 — 把孤島 surface 接成可達的 app 導航。純資料/純函式（無 React、
 * 無 DOM），導航的 reducer/路由全在此，AppShell 只負責掛載與點擊熱區。
 *
 * 設計：每個 tab 各自擁有一條 push/pop stack。stack 元素 = 一個 surface 畫面
 * （surface + scenario）。tab 切換保留各自 stack（鏡射 iOS 各 section 自有
 * NavigationStack 的行為）；同一 surface 的點擊熱區（書卡 / 單字本卡 / 今日複習
 * CTA）push 下一層畫面，back 退一層。
 *
 * 誠實邊界：web 只重寫了部分 surface，導航圖只連「fixtures 內真實可達」的畫面：
 *   bookshelf → reader（點書 → 靜態 reader chrome surface，pixel-complete）
 *   notebook  → vocabulary（點單字本卡 → 該本單字列表）
 *   notebook  → today-review（今日複習 CTA → 複習卡）
 *   podcast   → 直接是 player（web 無 podcast 列表 surface）
 *   overview  → 直接是統計儀表板（StatsPresenter；無下一層可達邊）
 */

/** stack 內一個畫面 = 一個 surface + 該 surface 的合法 scenario。 */
export type Screen = {
  [S in SurfaceId]: { surface: S; scenario: ScenarioId<S> }
}[SurfaceId]

/** 某 surface 的預設畫面（取該 surface taxonomy 首位 scenario）。 */
export function screenFor<S extends SurfaceId>(surface: S): Screen {
  return { surface, scenario: SURFACE_SCENARIOS[surface][0] } as Screen
}

/** 一個 tab 的導航狀態 = 非空 stack；末端 = 當前畫面。 */
export type TabStack = readonly [Screen, ...Screen[]]

/** 殼層整體導航狀態：當前 tab + 每個 surface-tab 的 stack。 */
export type NavState = {
  readonly tabId: string
  readonly stacks: Readonly<Record<string, TabStack>>
}

/** 某 surface-tab 的 root 畫面（stack 底）。 */
function rootScreenForTab(tabId: string): Screen | null {
  const tab = SHELL_TABS.find((t) => t.id === tabId)
  if (!tab || tab.kind !== 'surface') return null
  return screenFor(tab.surface)
}

/**
 * 初始導航狀態 — 每個 surface-tab 預先放好 root 畫面（單元素 stack）。
 * 初始 tab 由 URL 的 surface 決定（命中某 surface-tab 則選它，並用 URL scenario
 * 覆寫該 tab 的 root；否則落預設 bookshelf tab）。
 */
export function initialNavState(
  urlSurface?: SurfaceId,
  urlScenario?: string,
): NavState {
  const stacks: Record<string, TabStack> = {}
  for (const tab of SHELL_TABS) {
    if (tab.kind === 'surface') stacks[tab.id] = [screenFor(tab.surface)]
  }
  const match = SHELL_TABS.find((t) => t.kind === 'surface' && t.surface === urlSurface)
  let tabId = DEFAULT_TAB_ID
  if (match && match.kind === 'surface') {
    tabId = match.id
    const scenarios = SURFACE_SCENARIOS[match.surface] as readonly string[]
    if (urlScenario && scenarios.includes(urlScenario)) {
      stacks[match.id] = [{ surface: match.surface, scenario: urlScenario } as Screen]
    }
  }
  return { tabId, stacks }
}

/** 當前可見畫面（當前 tab 的 stack 末端）；placeholder tab → null。 */
export function currentScreen(state: NavState): Screen | null {
  const stack = state.stacks[state.tabId]
  return stack ? stack[stack.length - 1] : null
}

/** 當前 tab 的 stack 深度（placeholder tab → 0）。back 可用性 = depth > 1。 */
export function stackDepth(state: NavState): number {
  return state.stacks[state.tabId]?.length ?? 0
}

/** 切 tab：placeholder tab 不切（不可選），surface-tab 保留其既有 stack。 */
export function selectTab(state: NavState, tabId: string): NavState {
  const tab = SHELL_TABS.find((t) => t.id === tabId)
  if (!tab || tab.kind !== 'surface') return state
  return { ...state, tabId }
}

/** push 一個畫面到當前 tab 的 stack 末端。 */
export function push(state: NavState, screen: Screen): NavState {
  const stack = state.stacks[state.tabId]
  if (!stack) return state
  return {
    ...state,
    stacks: { ...state.stacks, [state.tabId]: [...stack, screen] as TabStack },
  }
}

/** pop 當前 tab 一層（已在 root 則 no-op）。 */
export function pop(state: NavState): NavState {
  const stack = state.stacks[state.tabId]
  if (!stack || stack.length <= 1) return state
  const next = stack.slice(0, -1) as unknown as TabStack
  return { ...state, stacks: { ...state.stacks, [state.tabId]: next } }
}

/**
 * 某畫面上某個熱區點擊 → 要 push 的下一個畫面（無對應 → null）。誠實導航圖
 * 的單一真相：只連 fixtures 內真實可達的 surface→surface 邊。
 */
export type NavIntent = 'open-book' | 'open-notebook' | 'open-today-review'

export function pushTargetFor(from: Screen, intent: NavIntent): Screen | null {
  if (from.surface === 'bookshelf' && intent === 'open-book') return screenFor('reader')
  if (from.surface === 'notebook' && intent === 'open-notebook') return screenFor('vocabulary')
  if (from.surface === 'notebook' && intent === 'open-today-review')
    return screenFor('today-review')
  return null
}

export { rootScreenForTab }
