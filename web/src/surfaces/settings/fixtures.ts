// Settings parity fixtures — 與 iOS Catalog `Settings` surface 的三個對拍
// scenario 一一對應（SettingsPresenter+Preview.swift 的 preview 資料形狀）。
// 文案/數字固化為 Catalog 快照當下的值；改這裡 = 改對拍基準，須同步 manifest。

import type { ScenarioId } from '../../harness/scenarios'

export interface LoggedInAccount {
  kind: 'logged-in'
  /** 帳號列顯示名（iOS 截斷後形態，含省略號時固化字面） */
  displayName: string
  email: string
  /** avatar 縮寫（兩字母） */
  initials: string
  /** PRO badge 是否掛在名字旁 */
  proBadge: boolean
  subscription:
    | { kind: 'active'; title: string; detail: string; pillLabel: string }
    | { kind: 'pricing-unavailable'; title: string; detail: string; pillLabel: string }
}

export interface LoggedOutAccount {
  kind: 'logged-out'
  heroTitle: string
  heroSubtitle: string
}

export interface SettingsFixture {
  account: LoggedInAccount | LoggedOutAccount
  /** 偏好區「自動同步」toggle；未登入時 iOS 不顯示此列 → null */
  autoSync: boolean | null
  /** 偏好區 footnote（登入版多一句自動同步說明） */
  preferencesFootnote: string
  /** 其他區「同步狀態」列 value；未登入無此列 → null */
  syncStatusValue: string | null
}

const PREFERENCES_FOOTNOTE_BASE = '切換後會立即套用到 app 介面。'
const PREFERENCES_FOOTNOTE_SYNC =
  PREFERENCES_FOOTNOTE_BASE + '開啟自動同步後，收錄滿 5 個單字會自動同步到雲端。'

const LOGGED_IN_BASE = {
  email: 'chen@example.com',
  initials: 'CL',
} as const

export const SETTINGS_FIXTURES: Record<ScenarioId<'settings'>, SettingsFixture> = {
  'subscribed-active': {
    account: {
      kind: 'logged-in',
      ...LOGGED_IN_BASE,
      displayName: 'Chen Lia...',
      proBadge: true,
      subscription: {
        kind: 'active',
        title: 'Pro 已啟用',
        detail: '年度方案，到期日 2027-03-10',
        pillLabel: '啟用中',
      },
    },
    autoSync: true,
    preferencesFootnote: PREFERENCES_FOOTNOTE_SYNC,
    syncStatusValue: '已連線 · 128 張 · 3 分鐘前',
  },
  'pricing-unavailable': {
    account: {
      kind: 'logged-in',
      ...LOGGED_IN_BASE,
      displayName: 'Chen Liang',
      proBadge: false,
      subscription: {
        kind: 'pricing-unavailable',
        title: 'Pro',
        detail: 'App Store 價格載入中，稍後會自動更新。',
        pillLabel: '升級',
      },
    },
    autoSync: true,
    preferencesFootnote: PREFERENCES_FOOTNOTE_SYNC,
    syncStatusValue: '已連線 · 128 張 · 10 分鐘前',
  },
  'logged-out': {
    account: {
      kind: 'logged-out',
      heroTitle: '解鎖完整功能',
      heroSubtitle: 'AI 翻譯 · 知識圖譜 · 雲端同步',
    },
    autoSync: null,
    preferencesFootnote: PREFERENCES_FOOTNOTE_BASE,
    syncStatusValue: null,
  },
}

/** 偏好區固定四列（自動同步另計，由 fixture.autoSync 控制） */
export const PREFERENCE_ROWS = [
  { label: '外觀', value: '跟隨系統', picker: true },
  { label: '翻譯語言', value: 'English → 繁體中文', picker: false },
  { label: '語言', value: '繁體中文', picker: true },
  { label: '複習節奏', value: '寬鬆', picker: false },
] as const
