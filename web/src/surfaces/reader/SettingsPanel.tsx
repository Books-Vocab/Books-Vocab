import type { ScenarioId } from '../../harness/scenarios'
import {
  SETTINGS_FIXTURES,
  SETTINGS_LINE_HEIGHT,
  SETTINGS_FONT_LABEL,
  SETTINGS_FONT_TONE,
  SETTINGS_THEMES,
  SETTINGS_SELECTED_THEME,
  SETTINGS_COLOR_SWATCHES,
  SETTINGS_SELECTED_COLOR,
} from './panel-fixtures'
import {
  BookOpenIcon,
  BookPagesIcon,
  ChevronDownIcon,
  LineSpacingIcon,
  MoonStarsIcon,
  SunIcon,
  XmarkIcon,
} from './icons'

/**
 * Reader · Settings 面板 — iOS ReaderSettingsPresenter（+Vocab layout）的 web 重寫（R3）。
 * 對齊 ReaderScenarios.swift「Reader · Settings」3 態（Normal / Bounds min / Bounds max，
 * bounds-max = PR #929）。幾何見 reader.css 的 rsettings 段。
 *
 * VocabCard 面板（drag handle + header + ScrollView 群組）：排版 / 外觀 / 生字標記 /
 * 開發者 四段，AppAirDivider 分隔。catalog 以 .fill 渲染，面板貼底升起、頂端漸出。
 */

const THEME_ICONS = { sun: SunIcon, book: BookOpenIcon, moon: MoonStarsIcon } as const

/** stepper「A」按鈕。enabled=false → 灰化（disabled 態，bounds min/max）。 */
function FontStepper({ size, enabled }: { size: 'small' | 'large'; enabled: boolean }) {
  return (
    <span className={`rsettings-stepper${enabled ? '' : ' is-disabled'}`} data-size={size}>
      A
    </span>
  )
}

export function SettingsPanel({ scenario }: { scenario: ScenarioId<'reader'> }) {
  const fixture = SETTINGS_FIXTURES[scenario]
  if (!fixture) return null

  // 行距 slider 填充比例：1.0…2.5 → 0…1。
  const lineFill = ((SETTINGS_LINE_HEIGHT - 1.0) / (2.5 - 1.0)) * 100

  return (
    <div className="rpanel rpanel-settings">
      <div className="rsettings-card">
        <span className="rsettings-handle" aria-hidden="true" />

        <header className="rsettings-header">
          <span className="rsettings-header-title">閱讀設定</span>
          <button type="button" className="rsettings-close" aria-label="關閉閱讀設定">
            <XmarkIcon size={14} strokeWidth={1.7} />
          </button>
        </header>

        <div className="rsettings-scroll">
          {/* ---- 排版 ---- */}
          <section className="rsettings-section">
            <h3 className="rsettings-section-title">排版</h3>
            <div className="rsettings-font-row">
              <FontStepper size="small" enabled={fixture.canDecreaseFontSize} />
              <span className="rsettings-font-size">{fixture.fontSizeText}</span>
              <FontStepper size="large" enabled={fixture.canIncreaseFontSize} />
            </div>
            <div className="rsettings-divider" />
            <div className="rsettings-line-row">
              <span className="rsettings-chip">
                <LineSpacingIcon size={14} strokeWidth={1.5} />
                行距
              </span>
              <span className="rsettings-slider">
                <span className="rsettings-slider-fill" style={{ width: `${lineFill}%` }} />
                <span className="rsettings-slider-knob" style={{ left: `${lineFill}%` }} />
              </span>
              <span className="rsettings-line-value">{SETTINGS_LINE_HEIGHT.toFixed(1)}</span>
            </div>
            <div className="rsettings-divider" />
            <div className="rsettings-mode-row">
              <span className="rsettings-chip">
                <BookPagesIcon size={14} strokeWidth={1.5} />
                閱讀模式
              </span>
              <div className="rsettings-mode-toggle">
                <span className="rsettings-tile is-selected">翻頁</span>
                <span className="rsettings-tile">捲動</span>
              </div>
            </div>
          </section>

          <div className="rsettings-air-divider" />

          {/* ---- 外觀 ---- */}
          <section className="rsettings-section">
            <h3 className="rsettings-section-title">外觀</h3>
            <div className="rsettings-font-menu">
              <span className="rsettings-font-menu-label">
                <span className="rsettings-font-menu-caption">字體</span>
                <span className="rsettings-font-menu-name">{SETTINGS_FONT_LABEL}</span>
              </span>
              <span className="rsettings-font-menu-trailing">
                <span className="rsettings-font-tone">{SETTINGS_FONT_TONE}</span>
                <ChevronDownIcon size={11} strokeWidth={2} />
              </span>
            </div>
            <div className="rsettings-theme-row">
              {SETTINGS_THEMES.map((theme) => {
                const Icon = THEME_ICONS[theme.icon]
                const selected = theme.label === SETTINGS_SELECTED_THEME
                return (
                  <span key={theme.label} className={`rsettings-theme-tile${selected ? ' is-selected' : ''}`}>
                    <span className="rsettings-theme-icon">
                      <Icon size={20} strokeWidth={1.5} />
                    </span>
                    <span className={`rsettings-theme-name${selected ? ' is-selected' : ''}`}>{theme.label}</span>
                    <span className="rsettings-theme-swatch" style={{ background: theme.swatch }} />
                  </span>
                )
              })}
            </div>
          </section>

          <div className="rsettings-air-divider" />

          {/* ---- 生字標記 ---- */}
          <section className="rsettings-section">
            <h3 className="rsettings-section-title">生字標記</h3>
            <span className="rsettings-sub-label">顏色</span>
            <div className="rsettings-color-row">
              {SETTINGS_COLOR_SWATCHES.map((swatch) => {
                const selected = swatch.label === SETTINGS_SELECTED_COLOR
                return (
                  <span key={swatch.label} className={`rsettings-color-tile${selected ? ' is-selected' : ''}`}>
                    <span className="rsettings-color-dot" style={{ background: swatch.hex }} />
                    <span className="rsettings-color-name">{swatch.label}</span>
                  </span>
                )
              })}
            </div>
            <div className="rsettings-divider" />
            <span className="rsettings-sub-label">濃度</span>
            <div className="rsettings-opacity-row">
              {['隱藏', '淡', '中', '深'].map((label) => (
                <span key={label} className={`rsettings-tile rsettings-opacity-tile${label === '中' ? ' is-selected' : ''}`}>
                  {label}
                </span>
              ))}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
