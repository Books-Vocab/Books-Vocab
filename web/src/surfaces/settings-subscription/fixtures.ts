import type { ScenarioId } from '../../harness/scenarios'

/** badgeTone → 色 token（SubscriptionBadgeTone.color(in:)）。
 *  neutral=secondaryText, accent=accent, success=success。 */
export type BadgeTone = 'neutral' | 'accent' | 'success'

export type SubscriptionFixture = {
  planName: string
  badgeText: string
  badgeTone: BadgeTone
  summary: string
  detail: string
  sourceLabel: string
  managementNote: string
  /** null = 不顯示 pricing-unavailable 卡片 */
  pricingUnavailableMessage: string | null
  restoreLabel: string
  restoreDescription: string
  isRestoreAvailable: boolean
  ctaTitle: string
  isRefreshing: boolean
}

/**
 * iOS SoT：SettingsFixtures.swift（subscribedActive / subscriptionLoading /
 * pricingUnavailable）+ SettingsSubscriptionSectionScenarios.inactiveFreeFixture。
 */
export const SETTINGS_SUBSCRIPTION_FIXTURES: Record<
  ScenarioId<'settings-subscription'>,
  SubscriptionFixture
> = {
  'pro-active': {
    planName: 'Pro',
    badgeText: '啟用中',
    badgeTone: 'success',
    summary: '年度方案，到期日 2027-03-10',
    detail: '感謝支持！所有進階功能已解鎖。',
    sourceLabel: 'App Store',
    managementNote: '訂閱狀態由 App Store 管理',
    pricingUnavailableMessage: null,
    restoreLabel: '恢復購買',
    restoreDescription: '如果您曾購買過訂閱',
    isRestoreAvailable: true,
    ctaTitle: '管理訂閱',
    isRefreshing: false,
  },
  loading: {
    planName: '—',
    badgeText: '載入中',
    badgeTone: 'neutral',
    summary: '正在確認訂閱狀態…',
    detail: '請稍候，系統正在與 App Store 通訊。',
    sourceLabel: '確認中',
    managementNote: '正在連線…',
    pricingUnavailableMessage: null,
    restoreLabel: '恢復購買',
    restoreDescription: '載入中…',
    isRestoreAvailable: false,
    ctaTitle: '重新整理',
    isRefreshing: true,
  },
  'pricing-unavailable': {
    planName: 'Pro',
    badgeText: '確認中',
    badgeTone: 'neutral',
    summary: '免費試用與月費將以 App Store 顯示為準。',
    detail: '目前已取得方案狀態，但價格資訊尚未回來；不影響你稍後進入訂閱頁。',
    sourceLabel: 'App Store',
    managementNote: '價格與試用週期會在 App Store 完整顯示。',
    pricingUnavailableMessage: 'App Store 價格載入中，稍後會自動更新。',
    restoreLabel: '可恢復購買',
    restoreDescription: '若先前已訂閱但此處顯示未啟用，可在訂閱頁使用恢復購買。',
    isRestoreAvailable: true,
    ctaTitle: '開始免費試用',
    isRefreshing: false,
  },
  'inactive-free': {
    planName: '免費方案',
    badgeText: '未訂閱',
    badgeTone: 'neutral',
    summary: '升級 Pro 解鎖知識圖譜與播客。',
    detail: '目前使用免費額度，部分進階功能受限。',
    sourceLabel: '無',
    managementNote: '尚未訂閱，可隨時於 App Store 開始。',
    pricingUnavailableMessage: null,
    restoreLabel: '恢復購買',
    restoreDescription: '曾經購買過？點此恢復先前的訂閱。',
    isRestoreAvailable: true,
    ctaTitle: '升級 Pro',
    isRefreshing: false,
  },
}
