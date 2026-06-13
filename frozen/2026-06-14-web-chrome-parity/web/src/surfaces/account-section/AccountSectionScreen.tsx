import type { ScenarioId } from '../../harness/scenarios'
import appIconUrl from '../../assets/app_icon.png'
import { ACCOUNT_SECTION_FIXTURES, type AccountSectionFixture, type LoggedInFixture, type LoggedOutFixture } from './fixtures'
import { useAuth } from '../../auth'
import { useAccountIdentityApiStore } from '../settings-account-detail/useAccountIdentityApiStore'
import { useEntitlementsApiStore } from '../settings-subscription/useEntitlementsApiStore'
import {
  AppleLogoIcon,
  CheckCircleFillIcon,
  ChevronRightIcon,
  PersonCircleIcon,
  SealCheckFillIcon,
  SparklesIcon,
  SparklesRectangleStackIcon,
  WarningTriangleFillIcon,
} from './icons'
import './account-section.css'

/**
 * Account Section · Section surface — iOS `SettingsAccountSection` 的 web 鏡像。
 *
 * 結構（SettingsAccountSection.swift）：
 *   VStack(spacing sectionGap=14)[
 *     SettingsSectionHeader(person.crop.circle, "帳號")
 *     .settingsCard {  // AppSectionCard padding 0、cardBackground、border、radius card
 *       logged-in：accountSummaryRow · divider · subscriptionRow · divider · 登出鈕(.appAction destructive)
 *       logged-out：hero(appIcon + displayTitle + body) · divider · [Google/Apple 鈕] · (auth-error 卡)
 *     }
 *   ]
 *
 * catalog scene = .fill（1179×2556、畫布透明 corner srgba 0,0,0,0），scene = 元件
 * 於 ScrollView 內 .padding(24) → 內容**頂部對齊**、水平內縮 24。故走全 phone-frame
 * 透明捕捉：surface 撐滿、justify flex-start、水平 padding 24；phone-frame 透明，
 * shots transparent:true → 內容-over-transparent，與 ref 對等。
 *
 * 幾何沿用 settings surface 已對 catalog 校準的 measured 值（同一元件、同一 catalog）。
 */
export function AccountSectionScreen({ scenario }: { scenario: ScenarioId<'account-section'> }) {
  const shell = new URLSearchParams(window.location.search).get('shell') === '1'
  if (shell) {
    return <AccountSectionScreenApi scenario={scenario} />
  }
  return <AccountSectionBody fixture={ACCOUNT_SECTION_FIXTURES[scenario]} />
}

function AccountSectionScreenApi({ scenario }: { scenario: ScenarioId<'account-section'> }) {
  const { login, logout } = useAuth()
  const { identity, status: idStatus } = useAccountIdentityApiStore()
  const { view, status: entStatus } = useEntitlementsApiStore()

  // 載入中：退回 scenario fixture（避免空白；幾何不變）。
  if (idStatus === 'loading' || entStatus === 'loading') {
    return <AccountSectionBody fixture={ACCOUNT_SECTION_FIXTURES[scenario]} />
  }

  if (!identity.isLoggedIn) {
    const fixture: LoggedOutFixture = {
      kind: 'logged-out',
      heroTitle: '解鎖完整功能',
      heroSubtitle: 'AI 翻譯・知識圖譜・雲端同步',
    }
    return <AccountSectionBody fixture={fixture} onLogin={login} />
  }

  const fixture: LoggedInFixture = {
    kind: 'logged-in',
    initials: identity.initials,
    displayName: identity.displayName,
    email: identity.email ?? '',
    proBadge: identity.isPro,
    subscription: {
      active: view.isActive,
      title: view.isActive ? 'Pro 已啟用' : view.planName,
      detail: view.isActive ? view.summary : view.detail,
      icon: view.isActive ? SealCheckFillIcon : SparklesRectangleStackIcon,
      iconActive: view.isActive,
      pillLabel: view.isActive ? view.badgeText : '升級',
      pillTone: view.isActive ? 'success' : 'accent',
    },
  }
  return <AccountSectionBody fixture={fixture} onLogout={logout} />
}

function AccountSectionBody({
  fixture,
  onLogin,
  onLogout,
}: {
  fixture: AccountSectionFixture
  onLogin?: (provider: 'google' | 'apple') => void
  onLogout?: () => void
}) {
  return (
    <div className="account-section-surface">
      <section className="account-section">
        <h2 className="account-section-header">
          <PersonCircleIcon size={15} />
          帳號
        </h2>
        {fixture.kind === 'logged-in' ? (
          <LoggedInCard fixture={fixture} onLogout={onLogout} />
        ) : (
          <LoggedOutCard fixture={fixture} onLogin={onLogin} />
        )}
      </section>
    </div>
  )
}

function LoggedInCard({ fixture, onLogout }: { fixture: LoggedInFixture; onLogout?: () => void }) {
  const sub = fixture.subscription
  const SubIcon = sub.icon
  return (
    <div className="account-card">
      {/* accountSummaryRow — SettingsAuthSummary */}
      <div className="account-row account-summary-row">
        <span className="account-avatar">{fixture.initials}</span>
        <span className="account-id">
          <span className="account-name-line">
            <span className="account-name">{fixture.displayName}</span>
            {fixture.proBadge && (
              <span className="account-pro-badge">
                <SparklesIcon size={12} />
                PRO
              </span>
            )}
          </span>
          <span className="account-email">{fixture.email}</span>
        </span>
        <CheckCircleFillIcon className="account-check" size={30} />
        <ChevronRightIcon className="account-chevron" size={10} strokeWidth={1.2} />
      </div>

      <div className="account-divider" />

      {/* subscriptionSummaryRow */}
      <div className="account-row account-subscription-row">
        <span className={sub.iconActive ? 'account-subscription-icon is-active' : 'account-subscription-icon'}>
          <SubIcon size={14} />
        </span>
        <span className="account-subscription-text">
          <span className="account-subscription-title">{sub.title}</span>
          <span className="account-subscription-detail">{sub.detail}</span>
        </span>
        <span className={sub.pillTone === 'success' ? 'account-pill is-success' : 'account-pill is-accent'}>
          {sub.pillLabel}
        </span>
        <ChevronRightIcon className="account-chevron" size={10} strokeWidth={1.2} />
      </div>

      <div className="account-divider" />

      {/* 登出鈕 — Button(.appAction(.destructive)).padding(cardPadding=18) */}
      <div className="account-signout-frame">
        <button className="account-signout" type="button" onClick={onLogout}>
          登出帳號
        </button>
      </div>
    </div>
  )
}

function LoggedOutCard({ fixture, onLogin }: { fixture: LoggedOutFixture; onLogin?: (provider: 'google' | 'apple') => void }) {
  return (
    <div className="account-card account-login-card">
      <div className="account-login-hero">
        {/* 實際 app icon 資產（ios AppIconImage.imageset），非自繪 mock */}
        <img className="account-login-appicon" src={appIconUrl} alt="" width={64} height={64} />
        <p className="account-login-title">{fixture.heroTitle}</p>
        <p className="account-login-subtitle">{fixture.heroSubtitle}</p>
      </div>

      <div className="account-divider" />

      <div className="account-login-actions">
        <button className="account-login-button" type="button" onClick={() => onLogin?.('google')}>
          <span className="account-social-badge is-google">G</span>
          <span className="account-login-button-label">
            以 <strong>Google</strong> 繼續
          </span>
          <ChevronRightIcon className="account-chevron" size={10} strokeWidth={1.2} />
        </button>
        <button className="account-login-button" type="button" onClick={() => onLogin?.('apple')}>
          <span className="account-social-badge is-apple">
            <AppleLogoIcon size={12} />
          </span>
          <span className="account-login-button-label">
            以 <strong>Apple</strong> 繼續
          </span>
          <ChevronRightIcon className="account-chevron" size={10} strokeWidth={1.2} />
        </button>

        {fixture.authError && (
          <div className="account-error-card">
            <div className="account-error-head">
              <WarningTriangleFillIcon className="account-error-icon" size={12} />
              <span className="account-error-title">{fixture.authError.title}</span>
            </div>
            <p className="account-error-desc">{fixture.authError.description}</p>
          </div>
        )}
      </div>
    </div>
  )
}
