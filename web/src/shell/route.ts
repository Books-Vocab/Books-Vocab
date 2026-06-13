import type { HarnessConfig } from '../harness/scenarios'
import { NAV_INTENTS, initialNavState, pushTargetFor, type NavState, type Screen } from './nav'
import { ROUTE_PREFIX, pathToNav } from './routeUrl'

/**
 * Shell 路由策略層 — 在 P1.1 codec（surface/scenario/param 合法性）之上再加
 * **nav-graph 可達性**驗證，並把「是否 shell 路徑 / 合法 / 404」收斂成單一決策，
 * 供殼層 mount 與 History API 共用（消除「壞輸入靜默落回預設」的盲區）。
 */

/** pathname 是否為 shell（/app）路由。 */
export function isAppPath(pathname: string): boolean {
  return pathname === ROUTE_PREFIX || pathname.startsWith(`${ROUTE_PREFIX}/`)
}

/**
 * stack 的每條相鄰邊是否都是誠實導航圖（pushTargetFor）真實產生的邊。codec 只保證
 * 各 surface/scenario 合法，**不保證** stack 是導航可達的——例如 /app/notebook/paywall
 * 的 surface 都合法卻無此邊。此函式遍歷 NAV_INTENTS 檢查每段 from→next 是否存在某
 * intent 使 pushTargetFor 落到 next.surface（params 不影響 surface 落點，故按 surface
 * 比對）。深度 1（純 root）無邊 → 恆可達。
 */
export function reachableStack(stack: readonly Screen[]): boolean {
  for (let i = 0; i < stack.length - 1; i++) {
    const from = stack[i]
    const nextSurface = stack[i + 1].surface
    const hasEdge = NAV_INTENTS.some((intent) => {
      const target = pushTargetFor(from, intent)
      return target !== null && target.surface === nextSurface
    })
    if (!hasEdge) return false
  }
  return true
}

export type RouteResolution =
  | { kind: 'valid'; nav: NavState }
  | { kind: 'notFound' }
  | { kind: 'nonShell' }

/**
 * 解析一個 pathname：
 *   - 非 /app → nonShell（呼叫端走 legacy ?shell=1 / config 初始化）
 *   - /app 但 codec null 或 stack 不可達 → notFound（落 404，不靜默 fallback）
 *   - 否則 valid + NavState
 */
export function resolveShellRoute(pathname: string): RouteResolution {
  if (!isAppPath(pathname)) return { kind: 'nonShell' }
  const nav = pathToNav(pathname)
  if (!nav) return { kind: 'notFound' }
  const stack = nav.stacks[nav.tabId]
  if (!stack || !reachableStack(stack)) return { kind: 'notFound' }
  return { kind: 'valid', nav }
}

/** 殼層初始狀態：當前 URL 是 /app 時依解析結果（valid → 該 nav；notFound → 標記
 *  404，nav 落 config 預設供 goHome 後顯示）；非 /app（legacy 入口）→ config 初始。 */
export function initialShellRoute(config: HarnessConfig): { nav: NavState; notFound: boolean } {
  const fallback = initialNavState(config.surface, config.scenario as string)
  if (typeof window === 'undefined') return { nav: fallback, notFound: false }
  const route = resolveShellRoute(window.location.pathname)
  if (route.kind === 'valid') return { nav: route.nav, notFound: false }
  if (route.kind === 'notFound') return { nav: fallback, notFound: true }
  return { nav: fallback, notFound: false }
}
