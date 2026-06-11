import type { ScenarioId } from '../../harness/scenarios'
import { SETTINGS_FIXTURES, PREFERENCE_ROWS } from './fixtures'
import './settings.css'

/**
 * Settings surface — iOS SettingsView/SettingsPresenter 的 web 重寫。
 * Phase 1 為可編譯骨架（結構 + fixture 接線）；幾何/樣式對齊在 Phase 2
 * 以 parity audit 驅動補上。
 */
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
          <h2 className="settings-section-header">帳號</h2>
          {account.kind === 'logged-in' ? (
            <div className="settings-card">
              <div className="settings-account-row">
                <span className="settings-avatar">{account.initials}</span>
                <span className="settings-account-name">{account.displayName}</span>
                {account.proBadge && <span className="settings-pro-badge">PRO</span>}
                <span className="settings-account-email">{account.email}</span>
              </div>
              <div className="settings-subscription-row">
                <span className="settings-subscription-title">{account.subscription.title}</span>
                <span className="settings-subscription-detail">{account.subscription.detail}</span>
                <span className="settings-subscription-pill">{account.subscription.pillLabel}</span>
              </div>
              <button className="settings-signout" type="button">
                登出帳號
              </button>
            </div>
          ) : (
            <div className="settings-card settings-login-card">
              <p className="settings-login-title">{account.heroTitle}</p>
              <p className="settings-login-subtitle">{account.heroSubtitle}</p>
              <button className="settings-login-button" type="button">
                以 Google 繼續
              </button>
              <button className="settings-login-button" type="button">
                以 Apple 繼續
              </button>
            </div>
          )}
        </section>

        <section className="settings-section">
          <h2 className="settings-section-header">偏好</h2>
          <div className="settings-card">
            {PREFERENCE_ROWS.map((row) => (
              <div className="settings-row" key={row.label}>
                <span className="settings-row-label">{row.label}</span>
                <span className="settings-row-value">{row.value}</span>
              </div>
            ))}
            {fixture.autoSync !== null && (
              <div className="settings-row">
                <span className="settings-row-label">自動同步</span>
                <span
                  className="settings-toggle"
                  data-on={fixture.autoSync}
                  role="switch"
                  aria-checked={fixture.autoSync}
                />
              </div>
            )}
          </div>
          <p className="settings-footnote">{fixture.preferencesFootnote}</p>
        </section>

        <section className="settings-section">
          <h2 className="settings-section-header">其他</h2>
          <div className="settings-card">
            {fixture.syncStatusValue !== null && (
              <div className="settings-row">
                <span className="settings-row-label">同步狀態</span>
                <span className="settings-row-value">{fixture.syncStatusValue}</span>
              </div>
            )}
            <div className="settings-row">
              <span className="settings-row-label">隱私政策</span>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
