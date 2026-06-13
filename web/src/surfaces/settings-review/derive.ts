import type { ReviewClockConfig, ReviewModeConfig } from '../../api/types'
import type { ParamRowFixture, ReviewFixture, ReviewMode } from './fixtures'

/**
 * settings-review 的純衍生 — 鏡像 iOS `SettingsReviewSection.swift` + `ReviewSettings.swift`：
 * 把後端 review_mode / review_clock config 映成顯示用 ReviewFixture，並提供 mode tile 點選、
 * pause toggle、custom 參數 stepper 的純狀態轉換（供 store 樂觀更新 + PUT /api/user/config）。
 *
 * 所有格式化 / 範圍 / 步進 / effective 值逐一對齊 iOS：
 *   formatHours：>=24 && h%24==0 → `${h/24}天`，否則 `${h}h`（Int 截斷）
 *   formatMultiplier：`%.2f×`
 *   pauseDescription：paused → `目前停在 {yMMMd}`，否則固定說明文
 *   effective（footer）：relaxed/intensive preset、custom 取 custom* 欄位
 */

export const PAUSE_DEFAULT = '暫停後，到期計算會停在現在；已到期卡仍可手動複習。'

/** mode + 5 custom 參數 + pause 的純值狀態（store 持有，map 自 config）。 */
export interface ReviewSettingsState {
  mode: ReviewMode
  customInitialIntervalHours: number
  customRememberedMultiplier: number
  customForgotMultiplier: number
  customMinimumIntervalHours: number
  customMaximumIntervalHours: number
  isPaused: boolean
  pausedAt: string | null // ISO8601
}

/** iOS ReviewSettings.default 對應的回退值（後端缺 review_mode 時用）。 */
export const REVIEW_SETTINGS_DEFAULT: ReviewSettingsState = {
  mode: 'relaxed',
  customInitialIntervalHours: 12,
  customRememberedMultiplier: 1.9,
  customForgotMultiplier: 0.45,
  customMinimumIntervalHours: 6,
  customMaximumIntervalHours: 1440,
  isPaused: false,
  pausedAt: null,
}

function normalizeMode(mode: string): ReviewMode {
  return mode === 'intensive' || mode === 'custom' ? mode : 'relaxed'
}

/** UserConfig 的 review_mode / review_clock → ReviewSettingsState（缺值套 default）。 */
export function stateFromConfig(
  reviewMode: ReviewModeConfig | null | undefined,
  reviewClock: ReviewClockConfig | null | undefined,
): ReviewSettingsState {
  const d = REVIEW_SETTINGS_DEFAULT
  return {
    mode: reviewMode ? normalizeMode(reviewMode.mode) : d.mode,
    customInitialIntervalHours: reviewMode?.custom_initial_interval_hours ?? d.customInitialIntervalHours,
    customRememberedMultiplier: reviewMode?.custom_remembered_multiplier ?? d.customRememberedMultiplier,
    customForgotMultiplier: reviewMode?.custom_forgot_multiplier ?? d.customForgotMultiplier,
    customMinimumIntervalHours: reviewMode?.custom_minimum_interval_hours ?? d.customMinimumIntervalHours,
    customMaximumIntervalHours: reviewMode?.custom_maximum_interval_hours ?? d.customMaximumIntervalHours,
    isPaused: reviewClock?.is_paused ?? d.isPaused,
    pausedAt: reviewClock?.paused_at ?? null,
  }
}

/** ReviewSettingsState → PUT /api/user/config 的 review_mode payload。 */
export function modeConfigFromState(s: ReviewSettingsState): ReviewModeConfig {
  return {
    mode: s.mode,
    custom_initial_interval_hours: s.customInitialIntervalHours,
    custom_remembered_multiplier: s.customRememberedMultiplier,
    custom_forgot_multiplier: s.customForgotMultiplier,
    custom_minimum_interval_hours: s.customMinimumIntervalHours,
    custom_maximum_interval_hours: s.customMaximumIntervalHours,
    updated_at: null,
  }
}

/** ReviewSettingsState → PUT /api/user/config 的 review_clock payload。 */
export function clockConfigFromState(s: ReviewSettingsState): ReviewClockConfig {
  return { is_paused: s.isPaused, paused_at: s.pausedAt, updated_at: null }
}

// MARK: - Formatters (iOS parity)

export function formatHours(hours: number): string {
  if (hours >= 24 && hours % 24 === 0) return `${Math.trunc(hours / 24)}天`
  return `${Math.trunc(hours)}h`
}

export function formatMultiplier(v: number): string {
  return `${v.toFixed(2)}×`
}

// MARK: - Effective values (footer)

export function effectiveInitialIntervalHours(s: ReviewSettingsState): number {
  switch (s.mode) {
    case 'relaxed': return 24
    case 'intensive': return 8
    case 'custom': return s.customInitialIntervalHours
  }
}
export function effectiveRememberedMultiplier(s: ReviewSettingsState): number {
  switch (s.mode) {
    case 'relaxed': return 2.5
    case 'intensive': return 1.4
    case 'custom': return s.customRememberedMultiplier
  }
}
export function effectiveForgotMultiplier(s: ReviewSettingsState): number {
  switch (s.mode) {
    case 'relaxed': return 0.5
    case 'intensive': return 0.35
    case 'custom': return s.customForgotMultiplier
  }
}
export function effectiveMinimumIntervalHours(s: ReviewSettingsState): number {
  switch (s.mode) {
    case 'relaxed': return 6
    case 'intensive': return 4
    case 'custom': return s.customMinimumIntervalHours
  }
}
export function effectiveMaximumIntervalHours(s: ReviewSettingsState): number {
  switch (s.mode) {
    case 'relaxed': return 1440
    case 'intensive': return 1440
    case 'custom': return s.customMaximumIntervalHours
  }
}

// MARK: - Custom param specs (range / step) — 對齊 SettingsReviewSection.adjustParam

type ParamKey =
  | 'customInitialIntervalHours'
  | 'customRememberedMultiplier'
  | 'customForgotMultiplier'
  | 'customMinimumIntervalHours'
  | 'customMaximumIntervalHours'

interface ParamSpec {
  key: ParamKey
  label: string
  step: number
  min: number
  max: number
  /** 'hours' → formatHours；'mult' → formatMultiplier */
  format: 'hours' | 'mult'
  /** can-dec/inc 比較是否套 ±0.001 epsilon（multiplier 用，避免浮點邊界誤判）。 */
  epsilon: boolean
}

export const PARAM_SPECS: ParamSpec[] = [
  { key: 'customInitialIntervalHours', label: '初始間隔', step: 4, min: 4, max: 72, format: 'hours', epsilon: false },
  { key: 'customRememberedMultiplier', label: '記得倍率', step: 0.1, min: 1.1, max: 5.0, format: 'mult', epsilon: true },
  { key: 'customForgotMultiplier', label: '忘記倍率', step: 0.05, min: 0.1, max: 0.9, format: 'mult', epsilon: true },
  { key: 'customMinimumIntervalHours', label: '最短間隔', step: 2, min: 2, max: 24, format: 'hours', epsilon: false },
  { key: 'customMaximumIntervalHours', label: '最長間隔', step: 120, min: 120, max: 8760, format: 'hours', epsilon: false },
]

function roundTo10(v: number): number {
  const f = 1e10
  return Math.round(v * f) / f
}

/** 套單一參數的 step delta + clamp（對齊 adjustParam：先 round(1e10) 再 clamp）。 */
export function adjustParam(
  s: ReviewSettingsState,
  key: ParamKey,
  delta: number,
): ReviewSettingsState {
  const spec = PARAM_SPECS.find((p) => p.key === key)
  if (!spec) return s
  const next = Math.min(spec.max, Math.max(spec.min, roundTo10(s[key] + delta)))
  return { ...s, [key]: next }
}

function canDecrement(value: number, spec: ParamSpec): boolean {
  return spec.epsilon ? value > spec.min + 0.001 : value > spec.min
}
function canIncrement(value: number, spec: ParamSpec): boolean {
  return spec.epsilon ? value < spec.max - 0.001 : value < spec.max
}

function paramRow(s: ReviewSettingsState, spec: ParamSpec): ParamRowFixture {
  const value = s[spec.key]
  return {
    label: spec.label,
    value: spec.format === 'hours' ? formatHours(value) : formatMultiplier(value),
    canDecrement: canDecrement(value, spec),
    canIncrement: canIncrement(value, spec),
  }
}

// MARK: - Display fixture

function pauseDescription(s: ReviewSettingsState): string {
  if (!s.isPaused) return PAUSE_DEFAULT
  if (!s.pausedAt) return '複習到期計算已暫停。'
  return `目前停在 ${formatPausedDate(s.pausedAt)}`
}

/** yMMMd template 的 zh 近似：`{y}年{M}月{d}日`（對齊 fixture「2024年12月6日」）。 */
export function formatPausedDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`
}

export function footerText(s: ReviewSettingsState): string {
  return `目前生效：初始 ${formatHours(effectiveInitialIntervalHours(s))}・記得 ${formatMultiplier(
    effectiveRememberedMultiplier(s),
  )}・忘記 ${formatMultiplier(effectiveForgotMultiplier(s))}・最短 ${formatHours(
    effectiveMinimumIntervalHours(s),
  )}・最長 ${formatHours(effectiveMaximumIntervalHours(s))}`
}

/** ReviewSettingsState → 顯示用 ReviewFixture（與 fixture 路徑同形）。 */
export function fixtureFromState(s: ReviewSettingsState): ReviewFixture {
  return {
    mode: s.mode,
    isPaused: s.isPaused,
    pauseDescription: pauseDescription(s),
    customRows: s.mode === 'custom' ? PARAM_SPECS.map((spec) => paramRow(s, spec)) : null,
    footer: footerText(s),
  }
}
