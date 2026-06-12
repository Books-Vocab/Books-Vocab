import type { ComponentType, SVGProps } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import { SealCheckFillIcon, SparklesRectangleStackIcon } from './icons'

type GlyphComponent = ComponentType<SVGProps<SVGSVGElement> & { size?: number; strokeWidth?: number }>

/** 訂閱列（logged-in 時出現）。對應 SettingsPresenterState.SubscriptionSection。 */
export interface SubscriptionFixture {
  active: boolean
  /** SettingsAccountCopy.subscriptionRowTitle：active → "Pro 已啟用"，否則 planName。 */
  title: string
  /** subscriptionRowSubtitle：active → summary｜detail；inactive → pricingUnavailableMessage｜summary。 */
  detail: string
  icon: GlyphComponent
  iconActive: boolean
  /** SettingsStatusBadge text：active → badgeText；inactive → "升級"。 */
  pillLabel: string
  /** badge tone：active(success) → success pill；inactive(accent) → accent pill。 */
  pillTone: 'success' | 'accent'
}

export interface LoggedInFixture {
  kind: 'logged-in'
  initials: string
  displayName: string
  email: string
  proBadge: boolean
  subscription: SubscriptionFixture
}

export interface LoggedOutFixture {
  kind: 'logged-out'
  heroTitle: string
  heroSubtitle: string
  /** VocabStateMessageCard：登入暫時失敗（auth error）。 */
  authError?: { title: string; description: string }
}

export type AccountSectionFixture = LoggedInFixture | LoggedOutFixture

/**
 * Account Section · Section fixtures — 對齊 SettingsAccountSectionScenarios.swift +
 * SettingsFixtures.swift。逐字對齊 displayName / email / planName / badgeText /
 * summary / detail / pricingUnavailableMessage。
 *
 * subtitle 推導（subscriptionRowSubtitle，SettingsAccountSection.swift L233）：
 *   active        → summary.isEmpty ? detail : summary
 *   inactive+價格未到 → pricingUnavailableMessage
 *   inactive      → summary
 */
export const ACCOUNT_SECTION_FIXTURES: Record<ScenarioId<'account-section'>, AccountSectionFixture> = {
  // SettingsFixtures .loggedOut（displayName "未登入"、email nil）→ 登入卡 hero。
  'logged-out': {
    kind: 'logged-out',
    heroTitle: '解鎖完整功能',
    heroSubtitle: 'AI 翻譯・知識圖譜・雲端同步',
  },
  // loggedOutWithError：同 loggedOut hero + authError 卡。
  'logged-out-auth-error': {
    kind: 'logged-out',
    heroTitle: '解鎖完整功能',
    heroSubtitle: 'AI 翻譯・知識圖譜・雲端同步',
    authError: {
      title: '登入暫時失敗',
      description: '無法連線至驗證伺服器，請稍後再試。',
    },
  },
  // .subscribedActive：isActive、planName "Pro"、badgeText "啟用中"(success)、
  // summary "年度方案，到期日 2027-03-10"。title = "Pro 已啟用"。
  'subscribed-active': {
    kind: 'logged-in',
    initials: 'CL',
    displayName: 'Chen Liang',
    email: 'chen@example.com',
    proBadge: true,
    subscription: {
      active: true,
      title: 'Pro 已啟用',
      detail: '年度方案，到期日 2027-03-10',
      icon: SealCheckFillIcon,
      iconActive: true,
      pillLabel: '啟用中',
      pillTone: 'success',
    },
  },
  // .subscriptionLoading：isActive false、planName "—"、badgeText "載入中"(neutral)、
  // summary "正在確認訂閱狀態…"。inactive → 升級 pill(accent)。title = planName "—"。
  'subscription-loading': {
    kind: 'logged-in',
    initials: 'CL',
    displayName: 'Chen Liang',
    email: 'chen@example.com',
    proBadge: false,
    subscription: {
      active: false,
      title: '—',
      detail: '正在確認訂閱狀態…',
      icon: SparklesRectangleStackIcon,
      iconActive: false,
      pillLabel: '升級',
      pillTone: 'accent',
    },
  },
  // .pricingUnavailable：isActive false、planName "Pro"、
  // pricingUnavailableMessage "App Store 價格載入中，稍後會自動更新。" → subtitle。
  // inactive → 升級 pill(accent)。title = planName "Pro"。
  'pricing-unavailable': {
    kind: 'logged-in',
    initials: 'CL',
    displayName: 'Chen Liang',
    email: 'chen@example.com',
    proBadge: false,
    subscription: {
      active: false,
      title: 'Pro',
      detail: 'App Store 價格載入中，稍後會自動更新。',
      icon: SparklesRectangleStackIcon,
      iconActive: false,
      pillLabel: '升級',
      pillTone: 'accent',
    },
  },
}
