import { useAuth } from './AuthContext'
import { AppHeroIcon, AppleLogoIcon, ChevronRightIcon, WarningTriangleFillIcon } from '../surfaces/login-sheet/icons'
import '../surfaces/login-sheet/login-sheet.css'

/**
 * 功能型登入閘門 — 視覺沿用 login-sheet.css，但按鈕為真 button，觸發 OAuth popup。
 * 這是 app 層入口，不是 catalog parity surface，因此允許互動 state。
 */
export function LoginGate() {
  const { login, devLogin, devLoginEnabled, error, isLoading } = useAuth()

  return (
    <div className="login-sheet-surface">
      <div className="login-sheet-content">
        <div className="login-sheet-spacer" />

        <div className="login-sheet-hero">
          <AppHeroIcon className="login-sheet-hero-icon" />
          <div className="login-sheet-hero-title">解鎖完整功能</div>
          <div className="login-sheet-hero-subtitle">AI 翻譯・知識圖譜・雲端同步</div>
        </div>

        <div className="login-sheet-spacer" />

        <div className="login-sheet-buttons">
          <button
            type="button"
            className="login-sheet-button"
            disabled={isLoading}
            onClick={() => login('google')}
          >
            <span className="login-sheet-badge login-sheet-badge--google">
              <span className="login-sheet-badge-letter">G</span>
            </span>
            <span className="login-sheet-button-title">以 Google 繼續</span>
            <span className="login-sheet-button-spacer" />
            <ChevronRightIcon className="login-sheet-button-chevron" size={10} strokeWidth={1} />
          </button>

          <button
            type="button"
            className="login-sheet-button"
            disabled={isLoading}
            onClick={() => login('apple')}
          >
            <span className="login-sheet-badge login-sheet-badge--apple">
              <AppleLogoIcon size={10} />
            </span>
            <span className="login-sheet-button-title">以 Apple 繼續</span>
            <span className="login-sheet-button-spacer" />
            <ChevronRightIcon className="login-sheet-button-chevron" size={10} strokeWidth={1} />
          </button>

          {/* dev/demo 登入 — 僅 dev server / mock 模式渲染；免後端、免 popup，
              直接寫入合成 session。ASCII-only 技術 label，不入 i18n。 */}
          {devLoginEnabled ? (
            <button
              type="button"
              className="login-sheet-button login-sheet-button--dev"
              data-testid="dev-login-button"
              disabled={isLoading}
              onClick={() => devLogin()}
            >
              <span className="login-sheet-badge login-sheet-badge--dev">
                <span className="login-sheet-badge-letter">D</span>
              </span>
              {/* i18n-allow: dev-only technical affordance, never shipped to prod+real */}
              <span className="login-sheet-button-title">Dev / Demo login (mock)</span>
              <span className="login-sheet-button-spacer" />
              <ChevronRightIcon className="login-sheet-button-chevron" size={10} strokeWidth={1} />
            </button>
          ) : null}
        </div>

        {error ? (
          <div className="login-sheet-error-wrap">
            <div className="login-sheet-error-card">
              <div className="login-sheet-error-content">
                <div className="login-sheet-error-head">
                  <WarningTriangleFillIcon className="login-sheet-error-icon" size={12} />
                  <div className="login-sheet-error-title">登入暫時失敗</div>
                  <span className="login-sheet-error-head-spacer" />
                </div>
                <div className="login-sheet-error-desc">{error}</div>
              </div>
            </div>
          </div>
        ) : null}
      </div>

      {isLoading ? (
        <div className="login-sheet-overlay">
          <div className="login-sheet-spinner" />
          <div className="login-sheet-overlay-label">正在驗證帳號…</div>
        </div>
      ) : null}
    </div>
  )
}
