import type { ScreenParams, Screen, NavState, TabStack } from './nav'
import { initialNavState } from './nav'
import { SURFACE_SCENARIOS, type SurfaceId } from '../harness/scenarios'
import { SHELL_TABS } from './tabs'

/**
 * URL ↔ NavState 投影 — 把殼層導航狀態序列化成可分享 / 可恢復的 URL 路徑，並
 * 反向解析回 NavState。純函式（無 DOM、無 history），History API 的整合（pushState /
 * popstate）由 P1.2 在殼層接線；本檔只負責「狀態 ⇄ 字串」的無損 codec。
 *
 * 設計（單一真相，零第二路由表）:
 *   路徑 = /app/<seg0>/<seg1>/...，每個 seg 對應 active tab 的 stack 一層（seg0 = 底）。
 *   seg = surface[@scenario][~k:v,k:v]
 *     - scenario 省略 ⇒ 該 surface 的預設（SURFACE_SCENARIOS[surface][0]）
 *     - params 省略 ⇒ 無 params（parity 相容的 param-free 畫面）
 *   tabId 不另存 URL：由 seg0.surface 反查 SHELL_TABS（root surface ↔ tab 一對一）。
 *
 * 誠實邊界：只服務 shell 模式；parity capture（?surface=&scenario=，pathname '/'）
 * 不經此 codec。非 /app 路徑、未知 surface/scenario、seg0 非 tab-root → 回 null，
 * 由呼叫端（P1.3）落 404，不靜默 fallback。
 */

export const ROUTE_PREFIX = '/app'

/** params 編碼的固定 key 順序 — 令 navToPath 輸出穩定（可比對、可快取）。 */
const PARAM_KEYS = ['notebookId', 'bookId', 'seriesId', 'epNum', 'word', 'format'] as const

function isSurfaceId(value: string): value is SurfaceId {
  return Object.prototype.hasOwnProperty.call(SURFACE_SCENARIOS, value)
}

function scenariosFor(surface: SurfaceId): readonly string[] {
  return SURFACE_SCENARIOS[surface] as readonly string[]
}

/** surface 是否為某 surface-tab 的 root（決定它能否當 seg0）。 */
function tabForRootSurface(surface: SurfaceId): string | null {
  const tab = SHELL_TABS.find((t) => t.kind === 'surface' && t.surface === surface)
  return tab ? tab.id : null
}

/**
 * value 編碼 — encodeURIComponent 已編 : , / @ 等分隔符，但**不編 `~`**（RFC3986
 * unreserved）。`~` 是 seg 的 params 分隔符，故額外手動編碼，讓 grammar 分隔符集
 * 與 payload 字元集完全不重疊（消除隱性脆弱依賴）。
 */
function encodeValue(value: string): string {
  return encodeURIComponent(value).replace(/~/g, '%7E')
}

function encodeParams(params: ScreenParams): string {
  const parts: string[] = []
  for (const key of PARAM_KEYS) {
    const value = params[key]
    if (value === undefined || value === null) continue
    parts.push(`${key}:${encodeValue(String(value))}`)
  }
  return parts.join(',')
}

/** 把單一 Screen 編碼成路徑 segment（surface[@scenario][~params]）。 */
function encodeScreen(screen: Screen): string {
  let seg: string = screen.surface
  const defaultScenario = scenariosFor(screen.surface)[0]
  if (screen.scenario !== defaultScenario) seg += `@${screen.scenario}`
  if (screen.params) {
    const encoded = encodeParams(screen.params)
    if (encoded) seg += `~${encoded}`
  }
  return seg
}

/**
 * 解析非空 params 段（`k:v,k:v`）；任何畸形或越域 → null（禁止靜默 fallback）：
 *   - 未知 key / 缺冒號 / 重複 key → null
 *   - epNum 非「非負整數」字面（空 / 小數 / 負 / hex / 科學記號）→ null
 *   - format 非 'epub'|'pdf'|'txt'|'md' → null（呼應 ScreenParams.format union，
 *     不讓 `as ScreenParams` cast 在髒值上撒謊）
 */
function decodeParams(paramsStr: string): ScreenParams | null {
  const params: Record<string, string | number> = {}
  for (const pair of paramsStr.split(',')) {
    const colon = pair.indexOf(':')
    if (colon < 0) return null
    const key = pair.slice(0, colon)
    if (!(PARAM_KEYS as readonly string[]).includes(key)) return null
    if (key in params) return null
    const raw = decodeURIComponent(pair.slice(colon + 1))
    if (key === 'epNum') {
      if (!/^\d+$/.test(raw)) return null
      params[key] = Number(raw)
    } else if (key === 'format') {
      if (raw !== 'epub' && raw !== 'pdf' && raw !== 'txt' && raw !== 'md') return null
      params[key] = raw
    } else {
      params[key] = raw
    }
  }
  return params as ScreenParams
}

/** 把單一路徑 segment 解碼回 Screen；任何不合法 → null。 */
function decodeScreen(seg: string): Screen | null {
  if (!seg) return null
  const tilde = seg.indexOf('~')
  const head = tilde >= 0 ? seg.slice(0, tilde) : seg

  const at = head.indexOf('@')
  const surface = at >= 0 ? head.slice(0, at) : head
  const scenarioRaw = at >= 0 ? head.slice(at + 1) : undefined

  if (!isSurfaceId(surface)) return null
  const scenarios = scenariosFor(surface)
  const scenario = scenarioRaw ?? scenarios[0]
  if (!scenarios.includes(scenario)) return null

  let params: ScreenParams = {}
  if (tilde >= 0) {
    const paramsStr = seg.slice(tilde + 1)
    if (paramsStr === '') return null // 空 `~` 非 canonical（navToPath 不輸出）
    const decoded = decodeParams(paramsStr)
    if (decoded === null) return null
    params = decoded
  }

  const screen = { surface, scenario } as Screen
  return Object.keys(params).length > 0 ? { ...screen, params } : screen
}

/** NavState → 可分享 URL 路徑（active tab 的 stack 投影）。 */
export function navToPath(state: NavState): string {
  const stack = state.stacks[state.tabId]
  if (!stack || stack.length === 0) return ROUTE_PREFIX
  return `${ROUTE_PREFIX}/${stack.map(encodeScreen).join('/')}`
}

/**
 * URL 路徑 → NavState；非殼層路徑 / 任何不合法 → null（呼叫端落 404，不 fallback）。
 * inactive tab 還原為各自預設 root（只 active tab 的 stack 完整保存於 URL）。
 */
export function pathToNav(path: string): NavState | null {
  if (path !== ROUTE_PREFIX && !path.startsWith(`${ROUTE_PREFIX}/`)) return null

  // 容忍單一尾斜線，但拒絕內部空 seg（雙斜線 /app//x）— navToPath 永不輸出空 seg，
  // 故空 seg = 畸形輸入，明確 null 而非靜默正規化。
  let rest = path.slice(ROUTE_PREFIX.length).replace(/\/$/, '')
  if (rest === '') return null // '/app' 或 '/app/'：無 tab seg
  const segs = rest.slice(1).split('/') // 去掉前導 '/' 再切
  if (segs.some((s) => s === '')) return null

  const screen0 = decodeScreen(segs[0])
  if (!screen0) return null
  const tabId = tabForRootSurface(screen0.surface)
  if (!tabId) return null

  const stack: Screen[] = [screen0]
  for (const seg of segs.slice(1)) {
    const screen = decodeScreen(seg)
    if (!screen) return null
    stack.push(screen)
  }

  const base = initialNavState()
  return {
    tabId,
    stacks: { ...base.stacks, [tabId]: stack as unknown as TabStack },
  }
}
