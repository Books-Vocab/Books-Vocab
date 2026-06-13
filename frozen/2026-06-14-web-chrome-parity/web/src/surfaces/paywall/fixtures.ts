import type { ScenarioId } from '../../harness/scenarios'

/**
 * Paywall fixtures — 逐字鏡像 iOS `SubscriptionPaywallSheet` 經 `SubscriptionPaywallCopy`
 * 解出的文案，輸入取自 `PaywallScenarios`（catalog DEBUG mock）。
 *
 * 關鍵衍生規則（productPrice = nil，因 catalog mock 無 StoreKit product，
 * 故所有金額皆 fallback 到 status.price_display）：
 *   billedAmount: admin→「管理員授權」/ price_display 有值→原樣 / 否則「載入 App Store 價格中…」
 *   trialInfo:    非 admin 且 days(7)>0 → 「包含 7 天免費試用」
 *   ctaButtonTitle: productPrice nil → 「訂閱」
 *   formattedExpiry: "yyyy/MM/dd HH:mm"，catalog TZ=Asia/Taipei（08:00Z→16:00）
 */

export type PaywallVariant = 'inactive' | 'active' | 'cancelled' | 'admin'

export interface FeatureItem {
  /** 'sparkles'（inactive marketing）| 'check'（active 已解鎖） */
  icon: 'sparkles' | 'check'
  title: string
  description?: string
}

export type ComparisonMark =
  | { kind: 'check'; pro: boolean } // check.circle.fill；pro=true→accent，false→success
  | { kind: 'label'; text: string; pro: boolean }

export interface ComparisonRow {
  title: string
  free: ComparisonMark
  pro: ComparisonMark
}

export interface PaywallFixture {
  variant: PaywallVariant
  /** hero symbol：inactive=sparkles.rectangle.stack.fill(accent) /
   *  active|admin=checkmark.seal.fill(success) / cancelled=exclamationmark.triangle.fill(accent) */
  heroIcon: 'stack' | 'seal' | 'triangle'
  heroTone: 'accent' | 'success'
  title: string
  summary: string
  /** inactive：InfoBlock title 用 sectionTitle(serif 18)；active：caption(sans 12 bold) */
  infoTitle: string
  infoSubtitle?: string
  infoDetail: string
  /** active 已解鎖列表 border = success@0.2；inactive marketing 列表 border = cardBorder */
  featureBorder: 'success' | 'card'
  features: FeatureItem[]
  comparison?: ComparisonRow[]
  /** 管理訂閱 primary（admin 隱藏）；inactive 無此鈕（用 CTA primary）。 */
  showManageButton: boolean
  /** inactive：CTA primary 標題（訂閱）；active/cancelled/admin：無 CTA primary，靠 manage */
  ctaPrimaryTitle?: string
  /** neutral 第二鈕：inactive=恢復購買 / active 系列=primaryActionTitle */
  neutralButtonTitle: string
  footerNote: string
  /** inactive 專屬：自動續訂揭露 */
  autoRenewNote?: string
}

const MARKETING_FEATURES: FeatureItem[] = [
  { icon: 'sparkles', title: 'AI 翻譯與語境解釋', description: '閱讀時即時查詢翻譯與語境' },
  { icon: 'sparkles', title: '雲端同步與跨裝置狀態', description: '生詞與閱讀進度跨裝置同步' },
  { icon: 'sparkles', title: '知識圖譜與關聯卡片', description: '視覺化詞彙關聯與間隔複習' },
]

const ACTIVE_FEATURES: FeatureItem[] = [
  { icon: 'check', title: 'AI 翻譯與語境解釋' },
  { icon: 'check', title: '雲端同步與跨裝置狀態' },
  { icon: 'check', title: '知識圖譜與關聯卡片' },
]

const COMPARISON_ROWS: ComparisonRow[] = [
  {
    title: '閱讀器（EPUB/PDF/TXT/MD）',
    free: { kind: 'check', pro: false },
    pro: { kind: 'check', pro: true },
  },
  {
    title: '本地生詞捕捉',
    free: { kind: 'check', pro: false },
    pro: { kind: 'check', pro: true },
  },
  {
    title: 'AI 翻譯與語境解釋',
    free: { kind: 'label', text: '有限', pro: false },
    pro: { kind: 'check', pro: true },
  },
  {
    title: '雲端同步與跨裝置狀態',
    free: { kind: 'label', text: '有限', pro: false },
    pro: { kind: 'check', pro: true },
  },
  {
    title: '知識圖譜與關聯卡片',
    free: { kind: 'label', text: '有限', pro: false },
    pro: { kind: 'check', pro: true },
  },
  {
    title: '間隔複習（Today Review）',
    free: { kind: 'label', text: '有限', pro: false },
    pro: { kind: 'check', pro: true },
  },
  {
    title: 'Podcast 跨集播放',
    free: { kind: 'label', text: '有限', pro: false },
    pro: { kind: 'check', pro: true },
  },
  {
    title: '每日 AI 額度',
    free: { kind: 'label', text: '1x', pro: false },
    pro: { kind: 'label', text: '10x', pro: true },
  },
]

export const PAYWALL_FIXTURES: Record<ScenarioId<'paywall'>, PaywallFixture> = {
  'admin-granted': {
    variant: 'admin',
    heroIcon: 'seal',
    heroTone: 'success',
    title: 'Pro 已啟用',
    summary: '目前帳號已由管理員授權為 Pro。',
    infoTitle: '管理員授權',
    infoDetail: '權限來源：管理員授權',
    featureBorder: 'success',
    features: ACTIVE_FEATURES,
    showManageButton: false,
    neutralButtonTitle: '重新整理權限狀態',
    footerNote: '此帳號目前由管理員授權為 Pro；若需延長、撤銷或調整，請聯絡管理員。',
  },
  inactive: {
    variant: 'inactive',
    heroIcon: 'stack',
    heroTone: 'accent',
    title: 'Books & Vocab Pro',
    summary:
      '解鎖閱讀器 AI、雲端同步、關聯圖與內建複習。免費試用與價格會直接來自 App Store。',
    infoTitle: '載入 App Store 價格中…',
    infoSubtitle: '包含 7 天免費試用',
    infoDetail: '權限來源：App Store 訂閱',
    featureBorder: 'card',
    features: MARKETING_FEATURES,
    comparison: COMPARISON_ROWS,
    showManageButton: false,
    ctaPrimaryTitle: '訂閱',
    neutralButtonTitle: '恢復購買',
    footerNote: '價格與免費試用長度會以 App Store 與你的地區顯示為準。',
    autoRenewNote:
      '訂閱將透過 Apple ID 自動續訂。可隨時在 App Store 設定中取消，取消後當期仍可使用至到期日。',
  },
  'pro-active-renewing': {
    variant: 'active',
    heroIcon: 'seal',
    heroTone: 'success',
    title: 'Pro 已啟用',
    summary: '感謝支持！所有進階功能已解鎖。',
    infoTitle: 'NT$90 / 月 · 包含 7 天免費試用',
    infoDetail: '權限來源：App Store 訂閱',
    featureBorder: 'success',
    features: ACTIVE_FEATURES,
    showManageButton: true,
    neutralButtonTitle: '重新同步訂閱狀態',
    footerNote: '價格與免費試用長度會以 App Store 與你的地區顯示為準。',
  },
  'pro-cancelled-but-active': {
    variant: 'cancelled',
    heroIcon: 'triangle',
    heroTone: 'accent',
    title: 'Pro 即將到期',
    summary: '你已取消自動續訂。Pro 功能可使用至 2026/06/20 16:00。',
    infoTitle: 'NT$90 / 月 · 包含 7 天免費試用',
    infoDetail: '權限來源：App Store 訂閱',
    featureBorder: 'success',
    features: ACTIVE_FEATURES,
    showManageButton: true,
    neutralButtonTitle: '重新同步訂閱狀態',
    footerNote: '到期後將回到免費方案。如需繼續使用 Pro，可重新訂閱。',
  },
}
