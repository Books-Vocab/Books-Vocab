import type { SubscriptionStatusResponse } from '../../api/types'

/**
 * 訂閱狀態投影（pure）—— 把後端 `SubscriptionStatusResponse`（GET /api/user/entitlements
 * 的 `pro`）投影成 settings-subscription / paywall 的展示 fixture。
 *
 * 對齊 iOS `SubscriptionPresentation`（KGSubscriptionStatus → badge/tone/摘要/詳情/CTA）
 * 與 `SubscriptionPaywallCopy`，並反映「web 無 StoreKit、純資訊呈現」的事實：
 *   - 不渲染可購買按鈕為可成交；CTA/manage 在 web 為純展示（informational only）。
 *   - 價格永遠取自後端 `price_display`（web 無 StoreKit product 可查）。
 *
 * 來源語意（對齊 iOS）：
 *   - source === 'admin' / 'admin_grant' → 管理員授權（無 App Store 管理路徑）
 *   - source === 'app_store'（或其他）→ App Store 管理
 *
 * 由 settings-subscription 與 paywall 兩 surface 共用，故抽為 pure 模組（無 React/IO）。
 */

export type SubscriptionBadgeTone = 'neutral' | 'accent' | 'success'

export interface SubscriptionView {
  isActive: boolean
  isAdmin: boolean
  planName: string
  badgeText: string
  badgeTone: SubscriptionBadgeTone
  summary: string
  detail: string
  /** 權限來源 label（App Store / 管理員授權 / 無）。 */
  sourceLabel: string
  /** 管理方式說明。 */
  managementNote: string
  /** 價格 / 試用顯示（取自 price_display，缺則 fallback 文案）。 */
  priceDisplay: string
  /** 已啟用且有到期日時的到期描述（缺則空字串）。 */
  expiryNote: string
  /** CTA 標題（active→管理訂閱 / inactive→升級 Pro）。 */
  ctaTitle: string
  /** 是否提供恢復購買 row（web 為純展示）。 */
  isRestoreAvailable: boolean
}

const PRICE_FALLBACK = 'App Store 價格載入中，稍後會自動更新。'

/** source 是否為管理員授權（涵蓋常見的 admin 來源字串）。 */
export function isAdminSource(source: string | null | undefined): boolean {
  if (!source) return false
  return source === 'admin' || source === 'admin_grant' || source.startsWith('admin')
}

/** 純函式：SubscriptionStatusResponse → SubscriptionView。null/缺值 = 未訂閱。匯出供測試。 */
export function projectSubscription(pro: SubscriptionStatusResponse | null): SubscriptionView {
  const active = pro?.is_active ?? false
  const admin = isAdminSource(pro?.source)
  const price = pro?.price_display ?? null

  if (active && admin) {
    return {
      isActive: true,
      isAdmin: true,
      planName: 'Pro',
      badgeText: '啟用中',
      badgeTone: 'success',
      summary: '目前帳號已由管理員授權為 Pro。',
      detail: '感謝支持！所有進階功能已解鎖。',
      sourceLabel: '管理員授權',
      managementNote: '此帳號由管理員授權，若需調整請聯絡管理員。',
      priceDisplay: '管理員授權',
      expiryNote: '',
      ctaTitle: '管理訂閱',
      isRestoreAvailable: false,
    }
  }

  if (active) {
    const planName = pro?.plan_name ?? 'Pro'
    const expiry = pro?.expires_at ?? null
    return {
      isActive: true,
      isAdmin: false,
      planName: 'Pro',
      badgeText: '啟用中',
      badgeTone: 'success',
      summary: expiry ? `Pro 已啟用，到期日 ${expiry}` : 'Pro 已啟用',
      detail: '感謝支持！所有進階功能已解鎖。',
      sourceLabel: 'App Store',
      managementNote: '訂閱狀態由 App Store 管理',
      priceDisplay: price ?? PRICE_FALLBACK,
      expiryNote: expiry ? `Pro 功能可使用至 ${expiry}。` : '',
      ctaTitle: planName ? '管理訂閱' : '管理訂閱',
      isRestoreAvailable: true,
    }
  }

  // 未訂閱（免費）。
  return {
    isActive: false,
    isAdmin: false,
    planName: '免費方案',
    badgeText: '未訂閱',
    badgeTone: 'neutral',
    summary: '升級 Pro 解鎖知識圖譜與播客。',
    detail: '目前使用免費額度，部分進階功能受限。',
    sourceLabel: '無',
    managementNote: '尚未訂閱，可隨時於 App Store 開始。',
    priceDisplay: price ?? PRICE_FALLBACK,
    expiryNote: '',
    ctaTitle: '升級 Pro',
    isRestoreAvailable: true,
  }
}
