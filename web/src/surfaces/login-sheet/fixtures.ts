import type { ScenarioId } from '../../harness/scenarios'

/**
 * Login Sheet fixtures — iOS LoginSheetScenarios.swift（CatalogPreviewAuth
 * isLoggedIn:false）。三 scenario 差異僅在 auth 狀態：
 *   Default        — 一般態（無 error / 非 authenticating）。
 *   Authenticating — isAuthenticating:true → 顯示 overlay。
 *   Error          — authError 非空 → 顯示錯誤卡。
 */
export interface LoginSheetFixture {
  isAuthenticating: boolean
  authError: string | null
}

export const LOGIN_SHEET_FIXTURES: Record<ScenarioId<'login-sheet'>, LoginSheetFixture> = {
  authenticating: { isAuthenticating: true, authError: null },
  default: { isAuthenticating: false, authError: null },
  error: { isAuthenticating: false, authError: '無法連線至伺服器，請稍後再試。' },
}
