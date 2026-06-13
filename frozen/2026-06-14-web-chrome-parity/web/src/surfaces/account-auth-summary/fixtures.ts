import type { ScenarioId } from '../../harness/scenarios'

/**
 * Account Section · Auth Summary fixtures —— iOS `SettingsAccountSectionScenarios`
 * 之 `AuthSummaryScene`（`SettingsAuthSummary(state:isProActive:)`）。
 *
 * - Initials · Free / Pro：state = SettingsFixtures.state(for: .subscribedActive).auth
 *   （userInitials "CL"、displayName "Chen Liang"、email "chen@example.com"）；
 *   isProActive 切換 PRO badge 顯隱。
 * - Long Name + Email Overflow：longIdentityState（initials "麥"、長中文名 + 超長 email）、
 *   isProActive: true，用以驗證 name/email lineLimit(1) 截斷。
 */
export interface AuthSummaryFixture {
  initials: string
  displayName: string
  email: string
  proBadge: boolean
}

export const ACCOUNT_AUTH_SUMMARY_FIXTURES: Record<
  ScenarioId<'account-auth-summary'>,
  AuthSummaryFixture
> = {
  'initials-free': {
    initials: 'CL',
    displayName: 'Chen Liang',
    email: 'chen@example.com',
    proBadge: false,
  },
  'initials-pro': {
    initials: 'CL',
    displayName: 'Chen Liang',
    email: 'chen@example.com',
    proBadge: true,
  },
  'long-name-email-overflow': {
    initials: '麥',
    displayName: '麥克斯韋爾・亞歷山大・陳良宇',
    email: 'an.extraordinarily.long.email.address@knowledge-graph.example.com',
    proBadge: true,
  },
}
