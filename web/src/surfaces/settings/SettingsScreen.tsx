import type { ScenarioId } from '../../harness/scenarios'
import appIconUrl from '../../assets/app_icon.png'
import { SETTINGS_FIXTURES, PREFERENCE_ROWS, EXTERNAL_ROWS } from './fixtures'
import type { LoggedInAccount, LoggedOutAccount } from './fixtures'
import {
  AppearanceIcon,
  AppleLogoIcon,
  CheckCircleFillIcon,
  ChevronRightIcon,
  DocTextIcon,
  EllipsisCircleIcon,
  HandRaisedIcon,
  LanguageBubbleIcon,
  PersonCircleIcon,
  QuestionCircleIcon,
  SealCheckFillIcon,
  SlidersIcon,
  SparklesIcon,
  StarIcon,
  SyncIcon,
  TimerIcon,
  TranslateIcon,
} from './icons'
import './settings.css'

/**
 * Settings surface — iOS SettingsView/SettingsPresenter 的 web 重寫。
 * 幾何常數逐一對齊 iOS（見 settings.css 的 px 註解）；結構順序 =
 * SettingsPresenter.swift：帳號 → 偏好 → 其他。
 */

const PREFERENCE_ICONS = {
  外觀: AppearanceIcon,
  翻譯語言: TranslateIcon,
  語言: LanguageBubbleIcon,
  複習節奏: TimerIcon,
} as const

const EXTERNAL_ICONS = {
  隱私政策: HandRaisedIcon,
  服務條款: DocTextIcon,
  支援: QuestionCircleIcon,
  '為 App 評分': StarIcon,
} as const

function SectionHeader({ icon: Icon, label }: { icon: typeof PersonCircleIcon; label: string }) {
  return (
    <h2 className="settings-section-header">
      <Icon size={15} />
      {label}
    </h2>
  )
}

/** Menu picker 的上下小 chevron（iOS Menu 的 trailing 指示）。 */
function PickerChevrons() {
  return (
    <svg className="settings-picker-chevrons" viewBox="0 0 10 16" width="10" height="16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M2 6l3-3.4L8 6M2 10l3 3.4L8 10" />
    </svg>
  )
}

function LoggedInCard({ account }: { account: LoggedInAccount }) {
  const sub = account.subscription
  return (
    <div className="settings-card">
      <div className="settings-row settings-account-row">
        <span className="settings-avatar">{account.initials}</span>
        <span className="settings-account-id">
          <span className="settings-account-name-line">
            <span className="settings-account-name">{account.displayName}</span>
            {account.proBadge && (
              <span className="settings-pro-badge">
                <SparklesIcon size={12} />
                PRO
              </span>
            )}
          </span>
          <span className="settings-account-email">{account.email}</span>
        </span>
        <CheckCircleFillIcon className="settings-account-check" size={30} />
        <ChevronRightIcon className="settings-chevron" size={10} strokeWidth={1.2} />
      </div>
      <div className="settings-divider" />
      <div className="settings-row settings-subscription-row">
        <span className={sub.active ? 'settings-subscription-icon is-active' : 'settings-subscription-icon'}>
          {sub.active ? <SealCheckFillIcon size={15} /> : <SparklesIcon size={15} />}
        </span>
        <span className="settings-subscription-text">
          <span className="settings-subscription-title">{sub.title}</span>
          <span className="settings-subscription-detail">{sub.detail}</span>
        </span>
        <span className={sub.active ? 'settings-pill is-active' : 'settings-pill'}>{sub.pillLabel}</span>
        <ChevronRightIcon className="settings-chevron" size={10} strokeWidth={1.2} />
      </div>
      <div className="settings-divider" />
      <div className="settings-signout-frame">
        <button className="settings-signout" type="button">
          登出帳號
        </button>
      </div>
    </div>
  )
}

function LoggedOutCard({ account }: { account: LoggedOutAccount }) {
  return (
    <div className="settings-card settings-login-card">
      <div className="settings-login-hero">
        {/* 實際 app icon 資產（ios AppIconImage.imageset），非自繪 mock */}
        <img className="settings-login-appicon" src={appIconUrl} alt="" width={64} height={64} />
        <p className="settings-login-title">{account.heroTitle}</p>
        <p className="settings-login-subtitle">{account.heroSubtitle}</p>
      </div>
      <div className="settings-divider" />
      <div className="settings-login-actions">
        <button className="settings-login-button" type="button">
          <span className="settings-social-badge is-google">G</span>
          <span className="settings-login-button-label">
            以 <strong>Google</strong> 繼續
          </span>
          <ChevronRightIcon className="settings-chevron" size={10} strokeWidth={1.2} />
        </button>
        <button className="settings-login-button" type="button">
          <span className="settings-social-badge is-apple">
            <AppleLogoIcon size={12} />
          </span>
          <span className="settings-login-button-label">
            以 <strong>Apple</strong> 繼續
          </span>
          <ChevronRightIcon className="settings-chevron" size={10} strokeWidth={1.2} />
        </button>
      </div>
    </div>
  )
}

export function SettingsScreen({ scenario }: { scenario: ScenarioId<'settings'> }) {
  const fixture = SETTINGS_FIXTURES[scenario]
  const { account } = fixture

  return (
    <div className="settings">
      <header className="settings-nav">
        <h1 className="settings-nav-title">設定</h1>
      </header>
      <div className="settings-scroll">
        <section className="settings-section">
          <SectionHeader icon={PersonCircleIcon} label="帳號" />
          {account.kind === 'logged-in' ? <LoggedInCard account={account} /> : <LoggedOutCard account={account} />}
        </section>

        <section className="settings-section">
          <SectionHeader icon={SlidersIcon} label="偏好" />
          <div className="settings-card">
            {PREFERENCE_ROWS.map((row, i) => {
              const Icon = PREFERENCE_ICONS[row.label]
              return (
                <div key={row.label}>
                  {i > 0 && <div className="settings-divider is-inset" />}
                  <div className="settings-row">
                    <span className="settings-row-icon">
                      <Icon size={row.iconSize} />
                    </span>
                    <span className="settings-row-label">{row.label}</span>
                    <span className="settings-row-value">{row.value}</span>
                    {row.nav ? (
                      <ChevronRightIcon className="settings-chevron" size={10} strokeWidth={1.2} />
                    ) : (
                      <PickerChevrons />
                    )}
                  </div>
                </div>
              )
            })}
            {fixture.autoSync !== null && (
              <div>
                <div className="settings-divider is-inset" />
                <div className="settings-row">
                  <span className="settings-row-icon">
                    <SyncIcon size={15} />
                  </span>
                  <span className="settings-row-label">自動同步</span>
                  <span
                    className="settings-toggle"
                    data-on={fixture.autoSync}
                    role="switch"
                    aria-checked={fixture.autoSync}
                    aria-label="自動同步"
                  />
                </div>
              </div>
            )}
          </div>
          <p className="settings-footnote">{fixture.preferencesFootnote}</p>
        </section>

        <section className="settings-section">
          <SectionHeader icon={EllipsisCircleIcon} label="其他" />
          <div className="settings-card">
            {fixture.syncStatusValue !== null && (
              <>
                <div className="settings-row">
                  <span className="settings-row-icon">
                    <SyncIcon size={15} />
                  </span>
                  <span className="settings-row-label">同步狀態</span>
                  <span className="settings-sync-status">
                    <span className="settings-sync-dot" />
                    {fixture.syncStatusValue}
                  </span>
                </div>
                <div className="settings-divider is-inset" />
              </>
            )}
            {EXTERNAL_ROWS.map((label, i) => {
              const Icon = EXTERNAL_ICONS[label]
              return (
                <div key={label}>
                  {i > 0 && <div className="settings-divider is-inset" />}
                  <div className="settings-row">
                    <span className="settings-row-icon">
                      <Icon size={15} />
                    </span>
                    <span className="settings-row-label">{label}</span>
                    <ChevronRightIcon className="settings-chevron" size={10} strokeWidth={1.2} />
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      </div>
    </div>
  )
}
