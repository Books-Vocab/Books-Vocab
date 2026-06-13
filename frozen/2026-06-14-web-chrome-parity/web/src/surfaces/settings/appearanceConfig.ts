import type { UserConfigResponse, VocabUIConfig } from '../../api/types'

/**
 * 外觀偏好（appearance/theme）持久化投影（pure）。
 *
 * 後端 `/api/user/config` 的 LWW 家族無專屬 appearance group；UI 偏好統一落在
 * `vocab_ui`（api_models/notebook.py::VocabUIConfig，web 端為 opaque
 * `[key: string]: unknown`）。故在此把 `appearance` 安全讀/寫進該 group 的一個鍵，
 * 不破壞 group 內其他既有鍵（patch 時保留 spread）。
 *
 * appearance 取值：'system' | 'light' | 'dark'（'system' = 跟隨系統，不顯式覆蓋主題）。
 */

export type AppearancePref = 'system' | 'light' | 'dark'

const VALID: ReadonlySet<string> = new Set<AppearancePref>(['system', 'light', 'dark'])

/** 純函式：從 config.vocab_ui.appearance 投影外觀偏好；缺/非法 → 'system'。匯出供測試。 */
export function appearanceFromConfig(config: UserConfigResponse | null): AppearancePref {
  const ui = (config?.vocab_ui ?? null) as Record<string, unknown> | null
  const raw = ui && typeof ui.appearance === 'string' ? ui.appearance : null
  return raw && VALID.has(raw) ? (raw as AppearancePref) : 'system'
}

/**
 * 純函式：把 appearance 併進現有 vocab_ui group（保留其他鍵），組成 PUT config 的
 * vocab_ui patch。匯出供測試。
 */
export function buildAppearancePatch(
  current: UserConfigResponse | null,
  appearance: AppearancePref,
): { vocab_ui: VocabUIConfig } {
  const existing = (current?.vocab_ui ?? {}) as Record<string, unknown>
  return { vocab_ui: { ...existing, appearance } }
}
