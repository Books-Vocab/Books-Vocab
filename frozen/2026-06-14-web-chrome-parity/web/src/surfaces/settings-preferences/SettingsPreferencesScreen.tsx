import type { ScenarioId } from '../../harness/scenarios'
import { SETTINGS_PREFERENCES_FIXTURES, type PreferencesFixture } from './fixtures'
import {
  AppearanceIcon,
  ChevronRightIcon,
  ChevronUpDownIcon,
  LanguageBubbleIcon,
  SlidersIcon,
  SyncIcon,
  TimerIcon,
  TranslateIcon,
} from './icons'
import './settings-preferences.css'

/**
 * Settings · Preferences Section surface — iOS `SettingsPreferencesSection` 的 web 鏡像。
 *
 * 結構（SettingsPreferencesSection.swift）：
 *   VStack(spacing sectionGap=14)[
 *     SettingsSectionHeader(slider.horizontal.3, "偏好")
 *     .settingsCard {  // AppSectionCard padding 0、.settings(skin)：cardBg、cardBorder 1px、radius card
 *       AppKeyValueRow(circle.lefthalf.filled "外觀") { SettingsMenuValue(appearance) }   // chevron.up.chevron.down
 *       SettingsDivider(inset 50)
 *       SettingsNavigationRow(textformat.abc "翻譯語言") { "src → tgt" + chevron.right }
 *       SettingsDivider(inset 50)
 *       AppKeyValueRow(character.bubble "語言") { SettingsMenuValue(language) }            // chevron.up.chevron.down
 *       SettingsDivider(inset 50)
 *       SettingsNavigationRow(timer "複習節奏") { reviewMode + chevron.right }
 *       (showAutoSync) SettingsDivider(inset 50) + AppKeyValueRow(arrow.triangle.2.circlepath "自動同步") { Toggle }
 *     }
 *     SettingsSectionFooter(footerText)
 *   ]
 *
 * AppKeyValueRow.settings：HStack(spacing s3=12)[icon(width 22, iconSmall 12 / secondary) ·
 *   label(body 15 / primary) · Spacer · content]、padding h cardPadding=18 / v 13、minHeight 50。
 * SettingsMenuValue：HStack(6)[text(caption 12 / secondary) · chevron.up.chevron.down(iconTiny 10 / tertiary)]。
 * SettingsStatusValue：caption 12 / secondaryText、trailing。
 *
 * catalog scene = .fill（1179×2556、畫布透明 corner srgba 0,0,0,0），scene = 元件於
 * ScrollView .padding(24) → 內容**頂部對齊**、水平內縮 24。故走全 phone-frame 透明捕捉
 * （非 crop=component）：surface 撐滿、justify flex-start、padding 24；phone-frame + surface
 * 透明，shots transparent:true → 內容-over-transparent，與 ref 對等。
 *
 * 幾何沿用 account-section（同一 settings card/header/divider 家族、同一 catalog）已校準的
 * measured 值：header 14px、card radius lg≈12、row v/h 13/18、divider hairline 0.34px。
 */
export function SettingsPreferencesScreen({ scenario }: { scenario: ScenarioId<'settings-preferences'> }) {
  const fixture: PreferencesFixture = SETTINGS_PREFERENCES_FIXTURES[scenario]
  return (
    <div className="settings-preferences-surface">
      <section className="settings-preferences">
        <h2 className="settings-preferences-header">
          <SlidersIcon size={15} />
          偏好
        </h2>

        <div className="settings-preferences-card">
          {/* 外觀 — AppKeyValueRow + SettingsMenuValue（picker） */}
          <div className="sp-row">
            <span className="sp-row-icon">
              <AppearanceIcon size={12} />
            </span>
            <span className="sp-row-label">外觀</span>
            <span className="sp-spacer" />
            <span className="sp-menu-value">
              <span className="sp-value-text">{fixture.selectedAppearance}</span>
              <ChevronUpDownIcon className="sp-menu-chevron" size={10} strokeWidth={1.4} />
            </span>
          </div>

          <div className="sp-divider" />

          {/* 翻譯語言 — SettingsNavigationRow + SettingsStatusValue + chevron.right */}
          <div className="sp-row">
            <span className="sp-row-icon">
              <TranslateIcon size={22} />
            </span>
            <span className="sp-row-label">翻譯語言</span>
            <span className="sp-spacer" />
            <span className="sp-nav-trailing">
              <span className="sp-status-value">{`${fixture.translationSource} → ${fixture.translationTarget}`}</span>
              <ChevronRightIcon className="sp-nav-chevron" size={10} strokeWidth={1.2} />
            </span>
          </div>

          <div className="sp-divider" />

          {/* 語言 — AppKeyValueRow + SettingsMenuValue（picker） */}
          <div className="sp-row">
            <span className="sp-row-icon">
              <LanguageBubbleIcon size={22} />
            </span>
            <span className="sp-row-label">語言</span>
            <span className="sp-spacer" />
            <span className="sp-menu-value">
              <span className="sp-value-text">{fixture.selectedLanguage}</span>
              <ChevronUpDownIcon className="sp-menu-chevron" size={10} strokeWidth={1.4} />
            </span>
          </div>

          <div className="sp-divider" />

          {/* 複習節奏 — SettingsNavigationRow + SettingsStatusValue + chevron.right */}
          <div className="sp-row">
            <span className="sp-row-icon">
              <TimerIcon size={22} />
            </span>
            <span className="sp-row-label">複習節奏</span>
            <span className="sp-spacer" />
            <span className="sp-nav-trailing">
              <span className="sp-status-value">{fixture.selectedReviewMode}</span>
              <ChevronRightIcon className="sp-nav-chevron" size={10} strokeWidth={1.2} />
            </span>
          </div>

          {fixture.showAutoSync ? (
            <>
              <div className="sp-divider" />
              {/* 自動同步 — AppKeyValueRow + Toggle（.tint accent） */}
              <div className="sp-row">
                <span className="sp-row-icon">
                  <SyncIcon size={22} />
                </span>
                <span className="sp-row-label">自動同步</span>
                <span className="sp-spacer" />
                <span
                  className={fixture.autoSyncEnabled ? 'sp-toggle is-on' : 'sp-toggle'}
                  role="switch"
                  aria-checked={fixture.autoSyncEnabled}
                >
                  <span className="sp-toggle-knob" />
                </span>
              </div>
            </>
          ) : null}
        </div>

        <p className="settings-preferences-footer">{footerText(fixture)}</p>
      </section>
    </div>
  )
}

/** 沿用 SettingsPreferencesSection.footerText：含 / 不含自動同步說明（無 autoLink scenario）。 */
function footerText(fixture: PreferencesFixture): string {
  return fixture.showAutoSync
    ? '切換後會立即套用到 app 介面。開啟自動同步後，收錄滿 5 個單字會自動同步到雲端。'
    : '切換後會立即套用到 app 介面。'
}
