import type { ScenarioId } from '../../harness/scenarios'
import {
  PAYWALL_FIXTURES,
  type ComparisonMark,
  type FeatureItem,
  type PaywallFixture,
} from './fixtures'
import { useEntitlementsApiStore } from '../settings-subscription/useEntitlementsApiStore'
import type { SubscriptionView } from '../settings-subscription/subscriptionProjection'
import {
  SparklesRectangleStackFillIcon,
  CheckmarkSealFillIcon,
  ExclamationmarkTriangleFillIcon,
  CheckmarkCircleFillIcon,
  SparklesIcon,
  ArrowUpForwardIcon,
} from './icons'
import './paywall.css'

/**
 * SubscriptionPaywallSheet — iOS 訂閱 paywall sheet 的 web 鏡像。
 *
 * NavigationStack + ScrollView，依 `hasProAccess` 分流：
 *   inactiveLayout（行銷式，左對齊）：sparkles hero → 大標 → summary(lineSpacing 6) →
 *     InfoBlock(sectionTitle 金額 + caption 試用/來源) → marketing feature list →
 *     Free vs Pro 對照表 → CTA primary + 恢復購買 → footer + 自動續訂揭露 → legal links
 *   activeLayout（確認式，hero 置中）：seal/triangle hero(置中) → 大標(置中) →
 *     summary(置中 lineSpacing 4) → 已解鎖 feature list → InfoBlock(caption 金額) →
 *     [管理訂閱 primary] + 重新同步 neutral → footer → legal links
 *
 * catalog scene = `.fill` 不透明（page-bg 填滿）→ 全 phone-frame 不透明捕捉，無 crop。
 * nav bar：status 59 + bar 44 = 103pt，inline title「訂閱」serif，量測近隱形（≈white）。
 */

export function PaywallScreen({ scenario }: { scenario: ScenarioId<'paywall'> }) {
  const shell = new URLSearchParams(window.location.search).get('shell') === '1'
  if (shell) {
    return <PaywallScreenApi />
  }
  return <PaywallScreenFixture scenario={scenario} />
}

function PaywallScreenFixture({ scenario }: { scenario: ScenarioId<'paywall'> }) {
  const f = PAYWALL_FIXTURES[scenario]
  return <PaywallBody f={f} />
}

/**
 * SubscriptionView（真實 entitlements 投影）→ 既有 PaywallFixture 形狀。web 無 StoreKit，
 * 故 active/admin 走確認式版面、inactive 走行銷式版面，但所有 CTA/manage 為純資訊（不可成交）。
 * 載入中以 inactive marketing 版面 + 價格載入文案呈現（與 fixture inactive 一致，避免空白）。
 */
export function fixtureFromView(view: SubscriptionView): PaywallFixture {
  if (view.isAdmin) {
    return { ...PAYWALL_FIXTURES['admin-granted'], infoTitle: view.priceDisplay }
  }
  if (view.isActive) {
    const base = PAYWALL_FIXTURES['pro-active-renewing']
    return {
      ...base,
      infoTitle: view.priceDisplay,
      summary: view.expiryNote || base.summary,
    }
  }
  // inactive：行銷式版面，價格取自後端（缺則 fixture 既有 fallback 文案）。
  const base = PAYWALL_FIXTURES.inactive
  return { ...base, infoTitle: view.priceDisplay || base.infoTitle }
}

function PaywallScreenApi() {
  const { view } = useEntitlementsApiStore()
  return <PaywallBody f={fixtureFromView(view)} />
}

function PaywallBody({ f }: { f: PaywallFixture }) {
  const isInactive = f.variant === 'inactive'

  const HeroIcon =
    f.heroIcon === 'stack'
      ? SparklesRectangleStackFillIcon
      : f.heroIcon === 'seal'
        ? CheckmarkSealFillIcon
        : ExclamationmarkTriangleFillIcon

  return (
    <div className="paywall-surface">
      {/* inline nav bar — title「訂閱」近隱形（ref 量測 ≈ white on page-bg） */}
      <div className="pw-nav">
        <span className="pw-nav-title">訂閱</span>
      </div>

      <div className="pw-scroll">
        <div className={`pw-content${isInactive ? ' pw-content-marketing' : ' pw-content-active'}`}>
          {isInactive ? (
            <>
              {/* Hero icon（左對齊） */}
              <HeroIcon className="pw-hero-icon" size={44} />

              <h1 className="pw-title">{f.title}</h1>
              <p className="pw-summary pw-summary-lead6">{f.summary}</p>

              {/* InfoBlock — 金額(sectionTitle) + 試用(caption) + 來源(caption) */}
              <div className="pw-info-block">
                <span className="pw-info-title-large">{f.infoTitle}</span>
                {f.infoSubtitle ? (
                  <span className="pw-info-subtitle">{f.infoSubtitle}</span>
                ) : null}
                <span className="pw-info-detail">{f.infoDetail}</span>
              </div>

              <FeatureList border={f.featureBorder} features={f.features} />

              {f.comparison ? <ComparisonTable rows={f.comparison} /> : null}

              {/* CTA primary + 恢復購買 neutral */}
              <div className="pw-actions">
                <button type="button" className="pw-btn pw-btn-primary">
                  <span className="pw-btn-label">{f.ctaPrimaryTitle}</span>
                  <span className="pw-btn-spacer" />
                </button>
                <button type="button" className="pw-btn pw-btn-neutral">
                  <span className="pw-btn-label">{f.neutralButtonTitle}</span>
                  <span className="pw-btn-spacer" />
                </button>
              </div>

              <p className="pw-footer-note">{f.footerNote}</p>
              {f.autoRenewNote ? (
                <p className="pw-footer-note">{f.autoRenewNote}</p>
              ) : null}
            </>
          ) : (
            <>
              {/* Hero（置中 VStack spacing controlGap 10），.padding(.top inlineGap 8） */}
              <div className="pw-hero">
                <HeroIcon
                  className={`pw-hero-icon pw-hero-icon-${f.heroTone}`}
                  size={44}
                />
                <h1 className="pw-title pw-title-center">{f.title}</h1>
                <p className="pw-summary pw-summary-center pw-summary-lead4">{f.summary}</p>
              </div>

              <FeatureList border={f.featureBorder} features={f.features} />

              {/* InfoBlock — priceLine(caption) + 來源(caption) */}
              <div className="pw-info-block">
                <span className="pw-info-title-small">{f.infoTitle}</span>
                <span className="pw-info-detail">{f.infoDetail}</span>
              </div>

              {/* 管理訂閱 primary（admin 隱藏）+ 重新同步 neutral */}
              <div className="pw-actions">
                {f.showManageButton ? (
                  <button type="button" className="pw-btn pw-btn-primary">
                    <span className="pw-btn-label">管理訂閱</span>
                    <span className="pw-btn-spacer" />
                    <ArrowUpForwardIcon className="pw-btn-trailing" size={12} />
                  </button>
                ) : null}
                <button type="button" className="pw-btn pw-btn-neutral">
                  <span className="pw-btn-label">{f.neutralButtonTitle}</span>
                  <span className="pw-btn-spacer" />
                </button>
              </div>

              <p className="pw-footer-note">{f.footerNote}</p>
            </>
          )}

          {/* legal links footer — 隱私政策 · 服務條款 */}
          <div className="pw-legal">
            <span className="pw-legal-link">隱私政策</span>
            <span className="pw-legal-sep">·</span>
            <span className="pw-legal-link">服務條款</span>
          </div>
        </div>
      </div>
    </div>
  )
}

function FeatureList({
  border,
  features,
}: {
  border: 'success' | 'card'
  features: FeatureItem[]
}) {
  return (
    <div className={`pw-feature-panel${border === 'success' ? ' pw-feature-panel-success' : ''}`}>
      {features.map((item) => (
        <div className="pw-feature-row" key={item.title}>
          {item.icon === 'check' ? (
            <CheckmarkCircleFillIcon className="pw-feature-icon pw-feature-icon-success" size={14} />
          ) : (
            <SparklesIcon className="pw-feature-icon pw-feature-icon-accent" size={14} />
          )}
          <div className="pw-feature-text">
            <span
              className={`pw-feature-title${item.description ? ' pw-feature-title-medium' : ''}`}
            >
              {item.title}
            </span>
            {item.description ? (
              <span className="pw-feature-desc">{item.description}</span>
            ) : null}
          </div>
        </div>
      ))}
    </div>
  )
}

function ComparisonTable({ rows }: { rows: { title: string; free: ComparisonMark; pro: ComparisonMark }[] }) {
  return (
    <div className="pw-feature-panel pw-compare">
      <div className="pw-compare-header">
        <span className="pw-compare-feature">功能</span>
        <span className="pw-compare-col pw-compare-col-free">Free</span>
        <span className="pw-compare-col pw-compare-col-pro">Pro</span>
      </div>
      {rows.map((row) => (
        <div key={row.title}>
          <div className="pw-compare-divider" />
          <div className="pw-compare-row">
            <span className="pw-compare-title">{row.title}</span>
            <span className="pw-compare-col">
              <Mark mark={row.free} />
            </span>
            <span className="pw-compare-col">
              <Mark mark={row.pro} />
            </span>
          </div>
        </div>
      ))}
    </div>
  )
}

function Mark({ mark }: { mark: ComparisonMark }) {
  if (mark.kind === 'check') {
    return (
      <CheckmarkCircleFillIcon
        className={`pw-mark-check ${mark.pro ? 'pw-mark-accent' : 'pw-mark-success'}`}
        size={14}
      />
    )
  }
  return (
    <span className={`pw-mark-label ${mark.pro ? 'pw-mark-accent-text' : 'pw-mark-secondary'}`}>
      {mark.text}
    </span>
  )
}
