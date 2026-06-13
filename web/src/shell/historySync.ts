import { useCallback, useEffect, useRef } from 'react'
import { initialNavState, type NavState } from './nav'
import { navToPath } from './routeUrl'
import { resolveShellRoute } from './route'

/**
 * NavState ⇄ History API 雙向綁定 — 把 P1.1 的純 codec（routeUrl）接上瀏覽器歷史，
 * 讓殼層導航可分享 URL、可 refresh 恢復、可 back/forward。
 *
 * 架構脈絡：web 有兩個獨立 NavState owner（mobile AppShell、tablet/desktop
 * ResponsiveShell），同一時刻只有一個「活躍」。故 hook 帶 `enabled` gate：每個殼層
 * 只在自己當值時綁定（mobile → AppShell，桌面 → ResponsiveShell），避免雙寫歷史。
 *
 * 真相方向：**(re-)enable 當下以 URL 為真相**（refresh / 斷點切換回來時 adopt URL，
 * 而非用可能 stale 的 nav 蓋掉 URL）；enable 後的穩態才 nav → URL（push）。決策邏輯
 * 抽成純函式 historySyncOp 以便 TDD；hook 只是薄套用層（DOM/history side-effect）。
 */

export type HistoryOp =
  | { kind: 'none'; path: string }
  | { kind: 'push'; path: string }
  | { kind: 'replace'; path: string }
  | { kind: 'adopt'; path: string; adopt: NavState }
  | { kind: 'notFound'; path: string }

/**
 * 純決策：給定當前 nav、瀏覽器 pathname、是否「剛 enable」，決定該對 history 做什麼。
 *   - URL 已同步 → none（不製造重複 entry）
 *   - 剛 enable + URL 是另一個合法 /app 路徑 → adopt（URL 為真相，回該 NavState）
 *   - 剛 enable + URL 非 /app 或不合法 → replace（normalize 到 nav 路徑，不加 entry）
 *   - 穩態 nav 改變 → push（新 history entry，供 back/forward）
 *
 * 註：「剛 enable + URL 是 /app 但不合法」目前 replace 到 nav 路徑（normalize）；
 * 明確的 404 由 P1.3 在呼叫端落（codec 不保證 nav-graph 可達性）。
 */
export function historySyncOp(args: {
  nav: NavState
  currentPath: string
  justEnabled: boolean
}): HistoryOp {
  const path = navToPath(args.nav)
  if (args.currentPath === path) return { kind: 'none', path }
  if (args.justEnabled) {
    const route = resolveShellRoute(args.currentPath)
    if (route.kind === 'valid') {
      // URL 解析出另一合法 nav → adopt（URL 為真相）；解析回同一 nav 但 currentPath
      // 非 canonical（trailing slash 等）→ replace normalize。
      return navToPath(route.nav) !== path
        ? { kind: 'adopt', path, adopt: route.nav }
        : { kind: 'replace', path }
    }
    // /app 但不合法/不可達 → 404（交呼叫端標記，不靜默 normalize）。
    if (route.kind === 'notFound') return { kind: 'notFound', path }
    // nonShell（legacy ?shell=1 在 '/'）→ normalize 到 /app 路徑。注意：normalize 只
    // 保留 nav-routable 狀態；appearance（theme 持久化層負責）與 login=1（一次性進場
    // 意圖）刻意不入 URL，refresh 不重現屬預期、非遺漏。
    return { kind: 'replace', path }
  }
  return { kind: 'push', path }
}

/**
 * 把 nav 雙向綁定到 History API，回傳 goHome（404 復原動作）。`enabled=false` 時
 * 完全不綁（讓另一殼層當值）。`notFound`=目前是否在顯示 404；為真時 nav→URL 同步
 * 停手（保留壞 URL 供使用者辨識，且令 effect 在 React StrictMode 雙invoke 下冪等）。
 * `onNotFound` 回報 URL 是否不合法/不可達（殼層據此渲染 404）。
 */
export function useShellHistory(
  nav: NavState,
  setNav: (next: NavState) => void,
  enabled = true,
  notFound = false,
  onNotFound?: (notFound: boolean) => void,
): () => void {
  const prevEnabled = useRef(false)

  // nav / enabled 變動 → 套用 history op。顯示 404 期間（notFound）不動 URL。
  useEffect(() => {
    if (!enabled) {
      prevEnabled.current = false
      return
    }
    if (notFound) return
    const justEnabled = !prevEnabled.current
    prevEnabled.current = true
    const op = historySyncOp({ nav, currentPath: window.location.pathname, justEnabled })
    switch (op.kind) {
      case 'adopt':
        onNotFound?.(false)
        setNav(op.adopt)
        break
      case 'notFound':
        onNotFound?.(true)
        break
      case 'push':
        window.history.pushState(null, '', op.path)
        break
      case 'replace':
        window.history.replaceState(null, '', op.path)
        break
      case 'none':
        break
    }
  }, [nav, enabled, notFound, setNav, onNotFound])

  // back/forward（popstate）→ 從 URL 還原 nav。pathname 已被瀏覽器設好，故還原後
  // nav→URL effect 會判定 in-sync（none），不製造迴圈。合法 → 還原；/app 不合法/
  // 不可達 → 標 404；非 shell URL → 不動（瀏覽器已離開 /app）。
  useEffect(() => {
    if (!enabled) return
    const onPop = () => {
      const route = resolveShellRoute(window.location.pathname)
      if (route.kind === 'valid') {
        onNotFound?.(false)
        setNav(route.nav)
      } else if (route.kind === 'notFound') {
        onNotFound?.(true)
      }
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [enabled, setNav, onNotFound])

  // 404 復原：在 event handler 內 pushState（不被 StrictMode 雙invoke）並清 notFound，
  // 令隨後的 effect 判定 in-sync，不會 re-404。
  return useCallback(() => {
    const home = initialNavState()
    if (enabled) window.history.pushState(null, '', navToPath(home))
    onNotFound?.(false)
    setNav(home)
  }, [enabled, setNav, onNotFound])
}
