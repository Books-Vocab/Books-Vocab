import type { ScenarioId, SurfaceId } from '../harness/scenarios'
import { SURFACE_SCENARIOS } from '../harness/scenarios'
import { DEFAULT_TAB_ID, SHELL_TABS } from './tabs'

/**
 * 殼層導航模型 — 把孤島 surface 接成可達的 app 導航。純資料/純函式（無 React、
 * 無 DOM），導航的 reducer/路由全在此，AppShell 只負責掛載與點擊熱區。
 *
 * 設計：每個 tab 各自擁有一條 push/pop stack。stack 元素 = 一個 surface 畫面
 * （surface + scenario + 可選 params）。tab 切換保留各自 stack（鏡射 iOS 各
 * section 自有 NavigationStack 的行為）；同一 surface 的點擊熱區（書卡 / 單字本卡 /
 * 今日複習 CTA / 單字列 / 設定列 / 播客集數）push 下一層畫面，back 退一層。
 *
 * 深層導航攜帶實體 id：Screen.params 是可選 bag，承載被點擊實體的真實 id
 * （notebookId / bookId / seriesId / epNum / word），令下游 surface 在 shell
 * 內顯示「該實體」而非預設 fixture。parity harness（無 shell）完全不經過此層，
 * 故 params 對 parity capture 零影響（fixture 畫面恆 param-free）。
 *
 * 誠實邊界：web 只重寫了部分 surface，導航圖只連「web 真實可達」的畫面：
 *   bookshelf      → reader（點書 → 靜態 reader chrome / live reader，帶 bookId）
 *   bookshelf      → settings（gear glyph → 設定；設定子樹由此 surface 接力可達）
 *   notebook       → vocabulary（點單字本卡 → 該本單字列表，帶 notebookId）
 *   notebook       → today-review（今日複習 CTA → 複習卡）
 *   notebook       → notebook-edit（編輯單字本 → 編輯 sheet surface）
 *   vocabulary     → word-detail-sheet（點單字列 → 單字詳情，帶 word）
 *   vocabulary     → vocab-add-link（新增連結入口）
 *   vocabulary     → knowledge-graph-view（知識圖譜 logged-out 空圖入口）
 *   vocabulary     → vocab-knowledge-graph（知識圖譜 live force graph 入口）
 *   podcast-home   → podcast-episode-list（系列 → 集數列表，帶 seriesId）
 *   podcast-episode-list → podcast（點集數 → 播放器，帶 seriesId/epNum）
 *   settings       → settings-review / settings-subscription /
 *                    settings-account-detail / translation-language-settings / sync
 *   overview       → 直接是統計儀表板（StatsPresenter；無下一層可達邊）
 */

/** 深層導航攜帶的實體識別子（皆可選；shell 路徑專用，parity 不經過）。 */
export type ScreenParams = {
  readonly notebookId?: string
  readonly bookId?: string
  readonly seriesId?: string
  readonly epNum?: number
  readonly word?: string
}

/** stack 內一個畫面 = 一個 surface + 該 surface 的合法 scenario + 可選 params。 */
export type Screen = {
  [S in SurfaceId]: { surface: S; scenario: ScenarioId<S>; params?: ScreenParams }
}[SurfaceId]

/**
 * 某 surface 的預設畫面（取該 surface taxonomy 首位 scenario）。
 * 可選帶入 params（深層導航攜帶實體 id）；省略則為 param-free 畫面（parity 相容）。
 */
export function screenFor<S extends SurfaceId>(surface: S, params?: ScreenParams): Screen {
  const screen: Screen = { surface, scenario: SURFACE_SCENARIOS[surface][0] } as Screen
  return params ? { ...screen, params } : screen
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

/**
 * 當前可見畫面的穩定路由識別子 — `tabId:depth:surface`。供 RouteTransition 的
 * AnimatePresence key 用：tab 切換、push/pop、同 tab 內換 surface 皆改變此鍵 →
 * 觸發轉場；同一畫面重渲染（params 變化等）不改鍵 → 不誤觸轉場。純函式，殼層
 * 與 parity 無關（parity 不經 nav）。
 */
export function routeKeyFor(state: NavState): string {
  const screen = currentScreen(state)
  return `${state.tabId}:${stackDepth(state)}:${screen?.surface ?? 'none'}`
}

/**
 * 當前可見畫面是否為「點書開啟的真閱讀器」(Live Reader / epub.js)。
 *
 * 條件 = 當前畫面 surface 為 reader 且 stack 深 >1（即由 bookshelf 的 open-book
 * push 進來，非 root）。兩個殼層（mobile AppShell、桌面/平板 ResponsiveShell）共用
 * 此謂詞決定「掛 LiveReaderScreen 取代靜態 parity ReaderScreen」，避免兩殼各自
 * inline fork 同一判斷而 drift（screenRegistry 註解強調的雙面風險）。
 *
 * 誠實邊界：parity capture（無殼層）不經 nav，故此謂詞對 ?surface=reader 對拍
 * 路徑零影響——該路徑恆渲染靜態 ReaderScreen。
 */
export function isLiveReaderScreen(state: NavState): boolean {
  const stack = state.stacks[state.tabId]
  if (!stack || stack.length <= 1) return false
  return stack[stack.length - 1].surface === 'reader'
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
 * 的單一真相：只連 web 真實可達的 surface→surface 邊。深層意圖可攜帶被點擊實體
 * 的 params（id），由 pushTargetFor 接力寫入目標畫面。
 */
export type NavIntent =
  // bookshelf
  | 'open-book'
  | 'open-settings'
  // notebook
  | 'open-notebook'
  | 'open-today-review'
  | 'edit-notebook'
  // vocabulary
  | 'open-word'
  | 'add-link'
  | 'open-knowledge-graph'
  | 'open-vocab-knowledge-graph'
  // podcast
  | 'open-podcast-series'
  | 'open-podcast-episode'
  // settings
  | 'open-settings-review'
  | 'open-settings-subscription'
  | 'open-settings-account'
  | 'open-settings-translation-language'
  | 'open-sync'

/**
 * 誠實導航圖：(from.surface, intent) → 下一畫面。params 可攜實體 id；省略 →
 * 落該 surface 的 param-free 預設畫面（仍合法可達）。
 */
export function pushTargetFor(
  from: Screen,
  intent: NavIntent,
  params?: ScreenParams,
): Screen | null {
  switch (from.surface) {
    case 'bookshelf':
      if (intent === 'open-book') return screenFor('reader', params)
      // gear glyph（iOS BookshelfView top-leading toolbar）→ 設定。設定子樹
      // （sync / subscription / account / translation）由此 surface 接力可達。
      if (intent === 'open-settings') return screenFor('settings')
      return null
    case 'notebook':
      if (intent === 'open-notebook') return screenFor('vocabulary', params)
      if (intent === 'open-today-review') return screenFor('today-review')
      if (intent === 'edit-notebook') return screenFor('notebook-edit', params)
      return null
    case 'vocabulary':
      if (intent === 'open-word') return screenFor('word-detail-sheet', params)
      if (intent === 'add-link') return screenFor('vocab-add-link')
      if (intent === 'open-knowledge-graph') return screenFor('knowledge-graph-view')
      // 知識圖譜（live force-directed graph，VocabKnowledgeGraphLive）— iOS
      // KnowledgeGraphPresenter 入口。knowledge-graph-view 為 logged-out 空圖
      // fixture；此邊落帶資料的互動圖。
      if (intent === 'open-vocab-knowledge-graph') return screenFor('vocab-knowledge-graph')
      return null
    case 'podcast-home':
      if (intent === 'open-podcast-series') return screenFor('podcast-episode-list', params)
      return null
    case 'podcast-episode-list':
      if (intent === 'open-podcast-episode') return screenFor('podcast', params)
      return null
    case 'settings':
      if (intent === 'open-settings-review') return screenFor('settings-review')
      if (intent === 'open-settings-subscription') return screenFor('settings-subscription')
      if (intent === 'open-settings-account') return screenFor('settings-account-detail')
      if (intent === 'open-settings-translation-language')
        return screenFor('translation-language-settings')
      // 同步狀態列（SettingsView「其他」section）→ sync 狀態畫面（SyncApiStore）。
      if (intent === 'open-sync') return screenFor('sync')
      return null
    default:
      return null
  }
}

export { rootScreenForTab }
