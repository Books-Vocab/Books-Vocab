import { MOCK_ACCESS_TOKEN } from '../api/mock/data'
import type { AuthSession } from './AuthContext'

/**
 * Phase 0 — 離線可用的 dev/demo 登入與 guest 進場決策（純函式，便於 node 環境單測）。
 *
 * 硬不變式：所有新行為僅在 dev 或 mock 模式生效，且只影響 ?shell=1 app 殼層。
 * parity capture 路徑（無 shell）完全不經過此模組。
 */

export const MOCK_USER_ID = 'mock-user'

/** import.meta.env 的最小可注入投影，供測試傳入。 */
export interface DevEnv {
  DEV?: boolean
  VITE_API_MODE?: string
}

/**
 * dev/demo 登入是否可用：開發伺服器（import.meta.env.DEV）或 mock 後端模式。
 * 生產 + real 後端時回 false → dev 按鈕不渲染、devLogin 不寫入合成 session。
 */
export function isDevLoginEnabled(env: DevEnv): boolean {
  return env.DEV === true || env.VITE_API_MODE === 'mock'
}

/**
 * 合成 session：直接套用 mock handler 接受的同一 literal token，免開 OAuth popup。
 * mock /auth/verify 也鑄造同一 token，故 dev 與真 verify 路徑產出一致的 Bearer。
 */
export function buildMockSession(): AuthSession {
  return { token: MOCK_ACCESS_TOKEN, userId: MOCK_USER_ID }
}

export type ShellAccess = 'loading' | 'guest' | 'full'

/**
 * App.tsx 的 ?shell=1 進場決策（與渲染解耦，可純測）：
 * - 仍在 hydrate localStorage → 'loading'（沿用既有 spinner 分支，不可破壞）。
 * - 已登入 → 'full'（完整功能）。
 * - 未登入 → 'guest'（鏡像 iOS guest tier：podcast 瀏覽可用、寫入面由下游 surface
 *   自行提示登入）。不再硬擋於 LoginGate；LoginGate 改由 guest 殼內 dev/demo 與
 *   登入入口可達。
 */
export function resolveShellAccess(state: {
  isLoading: boolean
  isLoggedIn: boolean
}): ShellAccess {
  if (state.isLoading) return 'loading'
  return state.isLoggedIn ? 'full' : 'guest'
}

/**
 * 資料畫面的 guest 空態 vs 真錯誤分類 — 'ok' | 'guest-empty' | 'error'。
 *
 * 殼層提供的單一真相純函式：把「data fetch 是否失敗」與「是否已登入」分流成下游
 * surface 的三態。未登入時（guest）無 token 必然取不到使用者資料，這**不是錯誤**而是
 * 「尚未登入」→ surface 應顯示登入引導空態（'guest-empty'），不可裸報系統錯誤；
 * 已登入仍失敗才是真錯誤（'error'，可重試）。Phase-2 bookshelf 以此把
 * useBookshelfApiStore 的 status='error'（guest 因無 token catch→error）正確分流，
 * 不再把「未登入」誤判成「載入失敗」。
 *
 * 不變式：isLoggedIn=false ⇒ 恆 'guest-empty'（無論 failed），因 guest 進場本就無
 * 個人資料可顯示；isLoggedIn=true 時才依 failed 落 'error' / 'ok'。
 */
export type DataState = 'ok' | 'guest-empty' | 'error'

export function classifyDataState(state: {
  isLoggedIn: boolean
  failed: boolean
}): DataState {
  if (!state.isLoggedIn) return 'guest-empty'
  return state.failed ? 'error' : 'ok'
}
