// Settings parity fixtures — 與 iOS Catalog `Settings` surface 的三個對拍
// scenario 一一對應（SettingsFixtures.swift / SettingsPresenter+Preview.swift
// 的 preview 資料形狀）。文案固化自 iOS SoT（SettingsAccountCopy.swift、
// zh-Hant.lproj）；改這裡 = 改對拍基準，須同步 manifest。

import type { ScenarioId } from '../../harness/scenarios'

export interface LoggedInAccount {
  kind: 'logged-in'
  /** 帳號列顯示名 — iOS fixture data 為完整名，截斷是 render 行為
   *  （CSS text-overflow），不固化進 data。 */
  displayName: string
  email: string
  /** avatar 縮寫（兩字母） */
  initials: string
  /** PRO badge 是否掛在名字旁 */
  proBadge: boolean
  /** 訂閱摘要列；active 與 pricing-unavailable 共用 shape，
   *  差異只在文案與 leading icon（由 active 旗標切）。 */
  subscription: { active: boolean; title: string; detail: string; pillLabel: string }
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
  displayName: 'Chen Liang',
  email: 'chen@example.com',
  initials: 'CL',
} as const

export const SETTINGS_FIXTURES: Record<ScenarioId<'settings'>, SettingsFixture> = {
  'subscribed-active': {
    account: {
      kind: 'logged-in',
      ...LOGGED_IN_BASE,
      proBadge: true,
      subscription: {
        active: true,
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
      proBadge: false,
      subscription: {
        active: false,
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
      // SettingsAccountCopy.marketingSubtitle：全形中點 U+30FB、無空格
      heroSubtitle: 'AI 翻譯・知識圖譜・雲端同步',
    },
    autoSync: null,
    preferencesFootnote: PREFERENCES_FOOTNOTE_BASE,
    syncStatusValue: null,
  },
}

/** 偏好區固定四列（自動同步另計，由 fixture.autoSync 控制）。
 *  外觀/語言是 Menu picker（上下 chevron）、翻譯語言/複習節奏是
 *  navigation row（右 chevron）——由 nav 旗標切 trailing 形態。 */
export const PREFERENCE_ROWS = [
  { label: '外觀', value: '跟隨系統', nav: false },
  { label: '翻譯語言', value: 'English → 繁體中文', nav: true },
  { label: '語言', value: '繁體中文', nav: false },
  { label: '複習節奏', value: '寬鬆', nav: true },
] as const

/** 其他區外部連結列（SettingsPresenter.swift externalActionItems）。
 *  852pt 快照只露出第一列，仍完整渲染維持結構正確。 */
export const EXTERNAL_ROWS = ['隱私政策', '服務條款', '支援', '為 App 評分'] as const
