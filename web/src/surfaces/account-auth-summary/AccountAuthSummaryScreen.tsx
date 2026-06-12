import type { ScenarioId } from '../../harness/scenarios'
import { ACCOUNT_AUTH_SUMMARY_FIXTURES } from './fixtures'
import { CheckCircleFillIcon, SparklesIcon } from './icons'
import './account-auth-summary.css'

/**
 * Account Section · Auth Summary surface —— iOS `SettingsAuthSummary`
 * （SettingsAccountSection.swift:341）的 web 鏡像，scene = `AuthSummaryScene`：
 * 元件 `.padding()`（rig 慣例 24）置於整 phone-frame，垂直置中。
 *
 * 元件 view tree（HStack spacing accountRowSpacing=14）：
 *   avatar（ZStack：Circle(mutedFill) frame 46 + initials sectionTitle/secondaryText）
 *   · VStack(.leading, spacing microGap=6)[
 *       HStack(spacing microGap=6)[Text(displayName) sectionTitle/primaryText lineLimit1
 *                                 · (isProActive ? SettingsProBadge)]
 *       · (email ? Text(email) caption/secondaryText lineLimit1)]
 *   · Spacer()
 *   · Image(checkmark.circle.fill) symbolLarge(30)/success
 *
 * 與 account-section（完整 section）差異：此 isolated row **無** trailing chevron、
 * **無** card chrome（scene 直接 .padding 於透明畫布）。
 *
 * catalog scene layout = .fill（1179×2556，corner srgba 0,0,0,0 透明）→ 全 phone-frame
 * 捕捉：surface 撐滿、垂直置中、水平內縮 scene padding 24；phone-frame + surface 透明，
 * shots transparent:true（omitBackground）→ web 與 ref 同為內容-over-transparent。
 */
export function AccountAuthSummaryScreen({
  scenario,
}: {
  scenario: ScenarioId<'account-auth-summary'>
}) {
  const fixture = ACCOUNT_AUTH_SUMMARY_FIXTURES[scenario]
  return (
    <div className="account-auth-summary-surface">
      <div className="account-auth-summary-row">
        <span className="account-auth-summary-avatar">{fixture.initials}</span>
        <span className="account-auth-summary-id">
          <span className="account-auth-summary-name-line">
            <span className="account-auth-summary-name">{fixture.displayName}</span>
            {fixture.proBadge && (
              <span className="account-auth-summary-pro-badge">
                <SparklesIcon size={12} />
                PRO
              </span>
            )}
          </span>
          <span className="account-auth-summary-email">{fixture.email}</span>
        </span>
        <CheckCircleFillIcon className="account-auth-summary-check" size={30} />
      </div>
    </div>
  )
}
