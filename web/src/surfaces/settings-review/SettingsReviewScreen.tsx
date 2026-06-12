import type { ScenarioId } from '../../harness/scenarios'
import { SETTINGS_REVIEW_FIXTURES, type ReviewMode, type ParamRowFixture } from './fixtures'
import {
  PauseCircleIcon,
  TimerIcon,
  SlidersIcon,
  HeartIcon,
  BoltIcon,
  GearShapeIcon,
  MinusIcon,
  PlusIcon,
} from './icons'
import './settings-review.css'

/**
 * Settings Sections · Review（複習節奏）surface — iOS `SettingsReviewSection`
 * 的 web 鏡像（catalog「Settings Sections · Review」）。
 *
 * 視圖樹（ScrollView > VStack spacing=sectionSpacing=24，pageHorizontalPadding=20
 * / pageTopPadding=12 / pageBottomPadding=48）：
 *   1. pauseSection — SettingsSectionHeader(pause.circle) + settingsCard（HStack
 *      [標題+說明 VStack · Spacer · Toggle]）
 *   2. modeSection — header(timer) + HStack(gap reviewModeTileGap=10)[3×
 *      SettingsSelectionTile] + footer
 *   3. customParamsSection（僅 custom）— header(slider.horizontal.3) +
 *      settingsCard[5× ParamRow，間插 SettingsDivider(leadingInset=50)]
 *   4. footerSection — SettingsSectionFooter「目前生效…」
 *
 * .fill layout → 全 phone-frame 捕捉、page-bg 不透明（同 bookshelf）；inline nav
 * title「複習節奏」在 page-bg 上以 primaryText 渲染（極淡，對拍 ref 一致）。
 */

const MODES: { mode: ReviewMode; label: string; Icon: typeof HeartIcon }[] = [
  { mode: 'relaxed', label: '寬鬆', Icon: HeartIcon },
  { mode: 'intensive', label: '密集', Icon: BoltIcon },
  { mode: 'custom', label: '自訂', Icon: GearShapeIcon },
]

export function SettingsReviewScreen({ scenario }: { scenario: ScenarioId<'settings-review'> }) {
  const fixture = SETTINGS_REVIEW_FIXTURES[scenario]

  return (
    <div className="settings-review">
      {/* inline nav title（UINavigationBar inline，page-bg 上 primaryText） */}
      <div className="settings-review-nav">
        <span className="settings-review-nav-title">複習節奏</span>
      </div>

      <div className="settings-review-scroll">
        <div className="settings-review-stack">
          {/* --- 暫停進度 --- */}
          <section className="settings-review-section">
            <SectionHeader icon={<PauseCircleIcon size={16} />} title="暫停進度" />
            <div className="settings-review-card settings-review-pause-card">
              <div className="settings-review-pause-text">
                <div className="settings-review-pause-title">凍結複習時鐘</div>
                <div className="settings-review-pause-desc">{fixture.pauseDescription}</div>
              </div>
              <div
                className="settings-review-toggle"
                data-on={fixture.isPaused ? '1' : undefined}
                role="switch"
                aria-checked={fixture.isPaused}
              >
                <span className="settings-review-toggle-knob" />
              </div>
            </div>
          </section>

          {/* --- 複習模式 --- */}
          <section className="settings-review-section">
            <SectionHeader icon={<TimerIcon size={16} />} title="複習模式" />
            <div className="settings-review-mode-row">
              {MODES.map(({ mode, label, Icon }) => {
                const selected = fixture.mode === mode
                return (
                  <div
                    key={mode}
                    className="settings-review-tile"
                    data-selected={selected ? '1' : undefined}
                  >
                    <Icon className="settings-review-tile-icon" size={15} />
                    <span className="settings-review-tile-label" data-selected={selected ? '1' : undefined}>
                      {label}
                    </span>
                  </div>
                )
              })}
            </div>
            <div className="settings-review-footer">選擇符合學習節奏的模式，設定立即生效。</div>
          </section>

          {/* --- 自訂參數（custom only）--- */}
          {fixture.customRows ? (
            <section className="settings-review-section">
              <SectionHeader icon={<SlidersIcon size={16} />} title="自訂參數" />
              <div className="settings-review-card">
                {fixture.customRows.map((row, i) => (
                  <div key={row.label}>
                    {i > 0 ? <div className="settings-review-divider" /> : null}
                    <ParamRow row={row} />
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          {/* --- footer「目前生效」 --- */}
          <div className="settings-review-footer">{fixture.footer}</div>
        </div>
      </div>
    </div>
  )
}

function SectionHeader({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <div className="settings-review-section-header">
      <span className="settings-review-section-header-icon">{icon}</span>
      <span className="settings-review-section-header-title">{title}</span>
    </div>
  )
}

function ParamRow({ row }: { row: ParamRowFixture }) {
  return (
    <div className="settings-review-param-row">
      <span className="settings-review-param-label">{row.label}</span>
      <div className="settings-review-stepper">
        <button
          type="button"
          className="settings-review-stepper-btn"
          data-disabled={row.canDecrement ? undefined : '1'}
        >
          <MinusIcon size={14} />
        </button>
        <span className="settings-review-param-value">{row.value}</span>
        <button
          type="button"
          className="settings-review-stepper-btn"
          data-disabled={row.canIncrement ? undefined : '1'}
        >
          <PlusIcon size={14} />
        </button>
      </div>
    </div>
  )
}
