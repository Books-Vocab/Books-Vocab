import type { ScenarioId } from '../../harness/scenarios'

/**
 * Settings Account Detail · fixtures — 逐字對齊 iOS
 * `SettingsAccountDetailScenarios.swift` + `SettingsFixtures.swift`。
 *
 * AuthSection 只取本 surface 用到的欄位：isLoggedIn / displayName / email。
 * DangerSection 只取 isDeletingAccount（nil = 無危險操作卡）。
 *
 *   subscribed-active：subscribedActive.auth（Chen Liang / chen@example.com）
 *                      + danger isDeletingAccount=false
 *   deleting-account： deletingAccount.auth（同上）+ danger isDeletingAccount=true
 *   logged-out：       loggedOutAuth（訪客 / nil email、isLoggedIn=false）+ danger=nil
 *   long-name-email-stress：longInfoAuth（超長 name/email）+ danger isDeletingAccount=false
 */

export interface DangerSection {
  isDeletingAccount: boolean
}

export interface AccountDetailFixture {
  isLoggedIn: boolean
  displayName: string
  /** nil/空 → 不渲染信箱列（iOS accountInfoItems 過濾） */
  email: string | null
  danger: DangerSection | null
}

export const SETTINGS_ACCOUNT_DETAIL_FIXTURES: Record<
  ScenarioId<'settings-account-detail'>,
  AccountDetailFixture
> = {
  'subscribed-active': {
    isLoggedIn: true,
    displayName: 'Chen Liang',
    email: 'chen@example.com',
    danger: { isDeletingAccount: false },
  },
  'deleting-account': {
    isLoggedIn: true,
    displayName: 'Chen Liang',
    email: 'chen@example.com',
    danger: { isDeletingAccount: true },
  },
  'logged-out': {
    isLoggedIn: false,
    displayName: '訪客',
    email: null,
    danger: null,
  },
  'long-name-email-stress': {
    isLoggedIn: true,
    displayName: '王小明的超級長英文混中文顯示名稱測試 Wonderfully Long Display Name',
    email: 'an.extremely.long.email.address.for.layout.testing@example-domain.com',
    danger: { isDeletingAccount: false },
  },
}
