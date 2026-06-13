import { createContext, useContext } from 'react'
import type { Screen, ScreenParams } from './nav'

/**
 * 殼層導航 context — 把 AppShell 的 push reducer + 當前畫面 params 暴露給渲染中的
 * surface，令 surface 內部的列/卡點擊可主動推進導航（attach 真實實體 id 的 Screen），
 * 並讓被導航進來的 surface 讀到攜帶的實體 id（如 vocabulary 顯示特定 notebookId）。
 *
 * API：
 *   navigate(target) — 以當前 tab push 一層（target = 完整 Screen，含 params）。
 *   params           — 當前畫面攜帶的實體 id bag（深層導航 push 進來的）；空 = {}。
 *
 * 誠實邊界：parity harness（無 shell）不掛此 provider，故 surface 在 parity 路徑
 * 取得 null context → navigate no-op、params 空，DOM 與 capture 行為完全不變。
 * surface 在 shell 內讀 params 時應「prop（nav 提供）優先於 window.location.search，
 * search 為 deep-link fallback」。
 */
export type ShellNav = {
  navigate: (target: Screen) => void
  params: ScreenParams
}

const ShellNavContext = createContext<ShellNav | null>(null)

export const ShellNavProvider = ShellNavContext.Provider

/**
 * 取得殼層導航 context。無 provider（parity 路徑 / 元件級 scene）→ 回 no-op +
 * 空 params，故 surface 可無條件呼叫 useShellNav() 而不需判斷是否在殼層內。
 */
export function useShellNav(): ShellNav {
  const ctx = useContext(ShellNavContext)
  return ctx ?? NOOP_NAV
}

const NOOP_NAV: ShellNav = { navigate: () => {}, params: {} }
