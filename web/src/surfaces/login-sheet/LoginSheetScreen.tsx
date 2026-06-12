import type { ScenarioId } from '../../harness/scenarios'
import { LOGIN_SHEET_FIXTURES } from './fixtures'
import { AppHeroIcon, AppleLogoIcon, ChevronRightIcon, WarningTriangleFillIcon } from './icons'
import './login-sheet.css'

/**
 * Auth · Login Sheet surface — iOS `LoginSheet`（Views/Auth/LoginSheet.swift）的
 * web 鏡像。
 *
 * content：VStack(s6)[ Spacer · hero VStack(s2)[AppHeroIcon · displayTitle ·
 * body] · Spacer · buttons VStack(controlGap)[Google · Apple] · (error card) ]，
 * overlay 於 isAuthenticating 蓋 pageBackground@0.85 + spinner + caption。
 *
 * catalog scene layout = .fill（全裝置幀、白系統底、Playbook 不顯 nav chrome）→
 * 全 phone-frame 不透明捕捉（無 crop、無 transparent flag）。
 */
export function LoginSheetScreen({ scenario }: { scenario: ScenarioId<'login-sheet'> }) {
  const fixture = LOGIN_SHEET_FIXTURES[scenario]
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
          <div className="login-sheet-button">
            <span className="login-sheet-badge login-sheet-badge--google">
              <span className="login-sheet-badge-letter">G</span>
            </span>
            <span className="login-sheet-button-title">以 Google 繼續</span>
            <span className="login-sheet-button-spacer" />
            <ChevronRightIcon className="login-sheet-button-chevron" size={10} strokeWidth={1} />
          </div>

          <div className="login-sheet-button">
            <span className="login-sheet-badge login-sheet-badge--apple">
              <AppleLogoIcon size={10} />
            </span>
            <span className="login-sheet-button-title">以 Apple 繼續</span>
            <span className="login-sheet-button-spacer" />
            <ChevronRightIcon className="login-sheet-button-chevron" size={10} strokeWidth={1} />
          </div>
        </div>

        {fixture.authError ? (
          <div className="login-sheet-error-wrap">
            <div className="login-sheet-error-card">
              <div className="login-sheet-error-content">
                <div className="login-sheet-error-head">
                  <WarningTriangleFillIcon className="login-sheet-error-icon" size={12} />
                  <div className="login-sheet-error-title">登入暫時失敗</div>
                  <span className="login-sheet-error-head-spacer" />
                </div>
                <div className="login-sheet-error-desc">{fixture.authError}</div>
              </div>
            </div>
          </div>
        ) : null}
      </div>

      {fixture.isAuthenticating ? (
        <div className="login-sheet-overlay">
          <div className="login-sheet-spinner" />
          <div className="login-sheet-overlay-label">正在驗證帳號…</div>
        </div>
      ) : null}
    </div>
  )
}
