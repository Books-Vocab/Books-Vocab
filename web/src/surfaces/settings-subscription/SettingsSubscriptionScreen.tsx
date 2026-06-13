import type { ReactNode } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import { SETTINGS_SUBSCRIPTION_FIXTURES, type BadgeTone, type SubscriptionFixture } from './fixtures'
import { useEntitlementsApiStore } from './useEntitlementsApiStore'
import type { SubscriptionView } from './subscriptionProjection'
import {
  SparklesRectangleStackIcon,
  KeyIcon,
  WrenchScrewdriverIcon,
  ArrowClockwiseIcon,
  InfoCircleIcon,
  ArrowClockwiseCircleIcon,
  ArrowRightCircleFillIcon,
  ChevronRightIcon,
  SpinnerIcon,
} from './icons'
import './settings-subscription.css'

/**
 * Settings Subscription Section — iOS `SettingsSubscriptionSection` 的 web 鏡像。
 *
 * 結構（VStack spacing=sectionGap 14）:
 *   1. SettingsSectionHeader「訂閱」+ sparkles.rectangle.stack（caption 12 bold secondaryText）
 *   2. settingsCard（cardBg + cardBorder 1px + radius-card 8）內 VStack(spacing 0):
 *        · InfoBlock（serif 18 plan title + caption summary/detail）+ trailing StatusBadge
 *          外包 cardPadding 18
 *        · AppSettingsDivider(leadingInset 50)
 *        · AppKeyValueRow 權限來源 / 管理方式 / [恢復購買]（icon22 + body15 label + trailing
 *          caption StatusValue），每列之間 divider
 *        · [PricingUnavailable VocabStateMessageCard，外包 cardPadding 18]
 *        · divider → CTA SettingsActionRowLabel（icon14 + body15 medium + chevron，minHeight 50）
 *   3. SettingsSectionFooter（caption 12 bold tertiaryText）
 *
 * catalog scene = `.fillH` → 元件級透明 crop（corner srgba 0,0,0,0）；scene wrapper
 * 採 SwiftUI `.padding()` 預設 16（≠ sort-pill 的 24）。
 */

const BADGE_TONE_CLASS: Record<BadgeTone, string> = {
  neutral: 'sub-badge-neutral',
  accent: 'sub-badge-accent',
  success: 'sub-badge-success',
}

export function SettingsSubscriptionScreen({
  scenario,
}: {
  scenario: ScenarioId<'settings-subscription'>
}) {
  const shell = new URLSearchParams(window.location.search).get('shell') === '1'
  if (shell) {
    return <SettingsSubscriptionScreenApi />
  }
  return <SettingsSubscriptionScreenFixture scenario={scenario} />
}

function SettingsSubscriptionScreenFixture({
  scenario,
}: {
  scenario: ScenarioId<'settings-subscription'>
}) {
  const f = SETTINGS_SUBSCRIPTION_FIXTURES[scenario]
  return <SettingsSubscriptionBody f={f} />
}

/** SubscriptionView（真實 entitlements 投影）→ 既有 SubscriptionFixture 形狀。 */
export function fixtureFromView(view: SubscriptionView, loading: boolean): SubscriptionFixture {
  if (loading) {
    return SETTINGS_SUBSCRIPTION_FIXTURES.loading
  }
  return {
    planName: view.planName,
    badgeText: view.badgeText,
    badgeTone: view.badgeTone,
    summary: view.summary,
    detail: view.detail,
    sourceLabel: view.sourceLabel,
    managementNote: view.managementNote,
    pricingUnavailableMessage: null,
    restoreLabel: '恢復購買',
    restoreDescription: view.isActive ? '如果您曾購買過訂閱' : '曾經購買過？點此恢復先前的訂閱。',
    isRestoreAvailable: view.isRestoreAvailable,
    ctaTitle: view.ctaTitle,
    isRefreshing: false,
  }
}

function SettingsSubscriptionScreenApi() {
  const { view, status } = useEntitlementsApiStore()
  const f = fixtureFromView(view, status === 'loading')
  return <SettingsSubscriptionBody f={f} />
}

function SettingsSubscriptionBody({ f }: { f: SubscriptionFixture }) {
  return (
    <div className="settings-subscription-surface">
      <div className="sub-section">
        {/* 1. Section header */}
        <div className="sub-section-header">
          <SparklesRectangleStackIcon className="sub-section-header-icon" />
          <span className="sub-section-header-title">訂閱</span>
        </div>

        {/* 2. settings card */}
        <div className="sub-card">
          {/* Plan info + badge */}
          <div className="sub-info-row">
            <div className="sub-info-block">
              <span className="sub-plan-title">{f.planName}</span>
              {f.summary ? <span className="sub-plan-summary">{f.summary}</span> : null}
              {f.detail ? <span className="sub-plan-detail">{f.detail}</span> : null}
            </div>
            <span className={`sub-badge ${BADGE_TONE_CLASS[f.badgeTone]}`}>{f.badgeText}</span>
          </div>

          <div className="sub-divider" />

          {/* meta row: 權限來源 */}
          <MetaRow icon={<KeyIcon className="sub-row-icon" />} label="權限來源">
            <span className="sub-status-value sub-status-secondary">{f.sourceLabel}</span>
          </MetaRow>

          <div className="sub-divider" />

          {/* meta row: 管理方式 */}
          <MetaRow icon={<WrenchScrewdriverIcon className="sub-row-icon" />} label="管理方式">
            <span className="sub-status-value sub-status-secondary sub-status-multi">
              {f.managementNote}
            </span>
          </MetaRow>

          {f.isRestoreAvailable ? (
            <>
              <div className="sub-divider" />
              <MetaRow
                icon={<ArrowClockwiseIcon className="sub-row-icon" />}
                label={f.restoreLabel}
              >
                <span className="sub-status-value sub-status-accent sub-status-multi">
                  {f.restoreDescription}
                </span>
              </MetaRow>
            </>
          ) : null}

          {f.pricingUnavailableMessage ? (
            <>
              <div className="sub-divider" />
              <div className="sub-pricing-wrap">
                <div className="sub-state-card">
                  <div className="sub-state-head">
                    {f.isRefreshing ? (
                      <ArrowClockwiseCircleIcon className="sub-state-icon" />
                    ) : (
                      <InfoCircleIcon className="sub-state-icon" />
                    )}
                    <span className="sub-state-title">
                      {f.isRefreshing ? '價格載入中' : '價格稍後更新'}
                    </span>
                  </div>
                  <span className="sub-state-desc">{f.pricingUnavailableMessage}</span>
                </div>
              </div>
            </>
          ) : null}

          <div className="sub-divider" />

          {/* CTA */}
          <div className={`sub-cta${f.isRefreshing ? ' sub-cta-disabled' : ''}`}>
            {f.isRefreshing ? (
              <SpinnerIcon className="sub-cta-spinner" />
            ) : (
              <ArrowRightCircleFillIcon className="sub-cta-icon" />
            )}
            <span className="sub-cta-title">{f.ctaTitle}</span>
            <span className="sub-cta-spacer" />
            <ChevronRightIcon className="sub-cta-chevron" />
          </div>
        </div>

        {/* 3. Footer */}
        <p className="sub-section-footer">
          Pro 權限由後端統一管理；來源可能是 App Store 訂閱或管理員手動授權。
        </p>
      </div>
    </div>
  )
}

function MetaRow({
  icon,
  label,
  children,
}: {
  icon: ReactNode
  label: string
  children: ReactNode
}) {
  return (
    <div className="sub-meta-row">
      <span className="sub-row-icon-box">{icon}</span>
      <span className="sub-row-label">{label}</span>
      <span className="sub-row-spacer" />
      {children}
    </div>
  )
}
