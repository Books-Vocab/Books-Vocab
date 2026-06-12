import type { ScenarioId } from '../../harness/scenarios'

/**
 * Settings Sections · Review（複習節奏）fixtures — 對齊 SettingsSectionsScenarios.swift
 * 「Settings Sections · Review」4 scenario 的 ReviewSettings 與其衍生顯示值。
 *
 * 衍生公式直接鏡像 SettingsReviewSection.swift + ReviewSettings.swift：
 *   formatHours：>=24 且整除 24 → `${h/24}天`，否則 `${h}h`
 *   formatMultiplier：`%.2f×`
 *   footer effective* 值：relaxed/intensive 為固定 preset、custom 取 custom* 欄位
 *   pauseDescription：未暫停=固定說明文；暫停=「目前停在 <yMMMd>」
 */

export type ReviewMode = 'relaxed' | 'intensive' | 'custom'

export interface ParamRowFixture {
  label: string
  value: string
  canDecrement: boolean
  canIncrement: boolean
}

export interface ReviewFixture {
  mode: ReviewMode
  /** toggle 開關 + 說明文（暫停時 toggle on、單行說明） */
  isPaused: boolean
  pauseDescription: string
  /** custom 模式才有的自訂參數列 */
  customRows: ParamRowFixture[] | null
  /** footer「目前生效」一行 */
  footer: string
}

const PAUSE_DEFAULT = '暫停後，到期計算會停在現在；已到期卡仍可手動複習。'

export const SETTINGS_REVIEW_FIXTURES: Record<ScenarioId<'settings-review'>, ReviewFixture> = {
  // 密集模式 — mode=intensive、未暫停
  intensive: {
    mode: 'intensive',
    isPaused: false,
    pauseDescription: PAUSE_DEFAULT,
    customRows: null,
    // effective: init 8h・rem 1.4・forg 0.35・min 4h・max 1440(=60天)
    footer: '目前生效：初始 8h・記得 1.40×・忘記 0.35×・最短 4h・最長 60天',
  },
  // 寬鬆模式 — mode=relaxed、未暫停
  relaxed: {
    mode: 'relaxed',
    isPaused: false,
    pauseDescription: PAUSE_DEFAULT,
    customRows: null,
    // effective: init 24(=1天)・rem 2.5・forg 0.5・min 6h・max 1440(=60天)
    footer: '目前生效：初始 1天・記得 2.50×・忘記 0.50×・最短 6h・最長 60天',
  },
  // 已凍結進度 — mode=relaxed、isProgressPaused=true、pausedAt=2024-12-06
  frozen: {
    mode: 'relaxed',
    isPaused: true,
    pauseDescription: '目前停在 2024年12月6日',
    customRows: null,
    footer: '目前生效：初始 1天・記得 2.50×・忘記 0.50×・最短 6h・最長 60天',
  },
  // 自訂模式 / 展開參數 — mode=custom、init 24/rem 2.1/forg 0.35/min 4/max 2160
  custom: {
    mode: 'custom',
    isPaused: false,
    pauseDescription: PAUSE_DEFAULT,
    customRows: [
      // init 24h → 1天；範圍 4..72，>4 可減、<72 可加
      { label: '初始間隔', value: '1天', canDecrement: true, canIncrement: true },
      // rem 2.1；範圍 1.1..5.0
      { label: '記得倍率', value: '2.10×', canDecrement: true, canIncrement: true },
      // forg 0.35；範圍 0.1..0.9
      { label: '忘記倍率', value: '0.35×', canDecrement: true, canIncrement: true },
      // min 4h；範圍 2..24，>2 可減
      { label: '最短間隔', value: '4h', canDecrement: true, canIncrement: true },
      // max 2160h → 90天；範圍 120..8760
      { label: '最長間隔', value: '90天', canDecrement: true, canIncrement: true },
    ],
    // effective(custom)=custom*: init 1天・rem 2.10・forg 0.35・min 4h・max 90天
    footer: '目前生效：初始 1天・記得 2.10×・忘記 0.35×・最短 4h・最長 90天',
  },
}
