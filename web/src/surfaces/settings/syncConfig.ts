import type { AutoLinkConfig, UserConfigResponse } from '../../api/types'

/**
 * 同步 / 自動連結偏好的純函式投影層（mirrors appearanceConfig.ts 的形狀）。
 *
 * `auto_link` group（api_models/graph.py::AutoLinkConfig）對 web 層 opaque，唯一
 * 語意鍵是 `enabled: bool`（缺 group / 缺鍵 = 開啟，向後相容，與後端預設 True 一致）。
 * `updated_at`（epoch 秒）為整組 LWW timestamp，由後端落地時蓋章；前端 patch 一律
 * 送 null 讓 server 自己 stamp（避免前端時鐘漂移污染 LWW 排序）。
 *
 * 同步狀態列從「現有可用訊號」推導（無新後端依賴）：
 *   - review_clock.is_paused → 自動同步是否暫停（暫停 = paused tone）
 *   - entitlements.pro.last_synced_at → 訂閱/雲端最後同步時間（相對格式化）
 *   - 皆缺 → 退回中性「已連線」。
 */

/** 從 config.auto_link.enabled 投影自動連結開關；缺/非 boolean → true（後端預設）。 */
export function autoLinkEnabled(config: UserConfigResponse | null): boolean {
  const al = (config?.auto_link ?? null) as Record<string, unknown> | null
  if (al && typeof al.enabled === 'boolean') return al.enabled
  return true
}

/**
 * 組 PUT config 的 auto_link patch：保留 group 內其他既有鍵、覆蓋 `enabled`，並把
 * `updated_at` 清成 null（交由後端 stamp LWW）。
 */
export function buildAutoLinkPatch(
  current: UserConfigResponse | null,
  enabled: boolean,
): { auto_link: AutoLinkConfig } {
  const existing = (current?.auto_link ?? {}) as Record<string, unknown>
  return { auto_link: { ...existing, enabled, updated_at: null } }
}

export type SyncTone = 'synced' | 'paused'

export interface SyncStatusView {
  /** 顯示文案（單行）。 */
  label: string
  /** 色調：synced = success dot；paused = muted（同步已暫停）。 */
  tone: SyncTone
}

export interface SyncSignals {
  /** entitlements.pro.last_synced_at（ISO8601）— 雲端/訂閱最後同步時間。可缺。 */
  lastSyncedAt?: string | null
  /** review_clock.is_paused — 自動同步是否暫停。 */
  isPaused?: boolean
  /** quota.fraction（0..1）— 目前未直接入文案，保留供未來擴充。 */
  quotaFraction?: number
  /** 注入「現在」epoch ms（測試可控；預設 Date.now()）。 */
  now?: number
}

/** 相對時間中文格式化（剛剛 / N 分鐘前 / N 小時前 / N 天前）。 */
function formatRelative(fromMs: number, nowMs: number): string {
  const diffSec = Math.max(0, Math.round((nowMs - fromMs) / 1000))
  if (diffSec < 60) return '剛剛'
  const mins = Math.floor(diffSec / 60)
  if (mins < 60) return `${mins} 分鐘前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小時前`
  const days = Math.floor(hours / 24)
  return `${days} 天前`
}

/** 從可用訊號推導同步狀態列（純函式）。 */
export function syncStatusFromSignals(signals: SyncSignals): SyncStatusView {
  if (signals.isPaused) {
    return { label: '自動同步已暫停', tone: 'paused' }
  }
  const now = signals.now ?? Date.now()
  if (signals.lastSyncedAt) {
    const t = Date.parse(signals.lastSyncedAt)
    if (!Number.isNaN(t)) {
      return { label: `已連線 · 上次同步 ${formatRelative(t, now)}`, tone: 'synced' }
    }
  }
  return { label: '已連線 · iCloud', tone: 'synced' }
}
