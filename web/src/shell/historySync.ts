import { useEffect, useRef } from 'react'
import type { NavState } from './nav'
import { navToPath, pathToNav } from './routeUrl'

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
    const fromUrl = pathToNav(args.currentPath)
    if (fromUrl && navToPath(fromUrl) !== path) return { kind: 'adopt', path, adopt: fromUrl }
    return { kind: 'replace', path }
  }
  return { kind: 'push', path }
}

/** 從當前瀏覽器 pathname 還原 NavState（shell URL）；非 shell URL / SSR → null。 */
export function navStateFromLocation(): NavState | null {
  if (typeof window === 'undefined') return null
  return pathToNav(window.location.pathname)
}

/**
 * 把 nav 雙向綁定到 History API。`enabled=false` 時完全不綁（讓另一殼層當值）。
 */
export function useShellHistory(
  nav: NavState,
  setNav: (next: NavState) => void,
  enabled = true,
): void {
  const prevEnabled = useRef(false)

  // nav / enabled 變動 → 套用 history op。
  useEffect(() => {
    if (!enabled) {
      prevEnabled.current = false
      return
    }
    const justEnabled = !prevEnabled.current
    prevEnabled.current = true
    const op = historySyncOp({ nav, currentPath: window.location.pathname, justEnabled })
    switch (op.kind) {
      case 'adopt':
        setNav(op.adopt)
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
  }, [nav, enabled, setNav])

  // back/forward（popstate）→ 從 URL 還原 nav。pathname 已被瀏覽器設好，故還原後
  // nav→URL effect 會判定 in-sync（none），不製造迴圈。非 shell URL → 不動。
  useEffect(() => {
    if (!enabled) return
    const onPop = () => {
      const restored = pathToNav(window.location.pathname)
      if (restored) setNav(restored)
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [enabled, setNav])
}
