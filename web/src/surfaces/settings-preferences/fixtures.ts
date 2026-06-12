import type { ScenarioId } from '../../harness/scenarios'

/**
 * Settings · Preferences fixtures — 對應 SettingsSectionsScenarios.swift 的
 * PreferencesSectionScene 三個 .fill scenario（SettingsPresenterState.PreferencesSection）。
 */
export interface PreferencesFixture {
  selectedAppearance: string
  translationSource: string
  translationTarget: string
  selectedLanguage: string
  selectedReviewMode: string
  autoSyncEnabled: boolean
  showAutoSync: boolean
}

export const SETTINGS_PREFERENCES_FIXTURES: Record<ScenarioId<'settings-preferences'>, PreferencesFixture> = {
  // 含自動同步
  'with-auto-sync': {
    selectedAppearance: '跟隨系統',
    translationSource: '英文',
    translationTarget: '繁體中文',
    selectedLanguage: '繁體中文',
    selectedReviewMode: '寬鬆',
    autoSyncEnabled: true,
    showAutoSync: true,
  },
  // 自動同步關閉
  'auto-sync-off': {
    selectedAppearance: '淺色',
    translationSource: '英文',
    translationTarget: '日本語',
    selectedLanguage: 'English',
    selectedReviewMode: '密集',
    autoSyncEnabled: false,
    showAutoSync: true,
  },
  // 未登入 / 無同步列
  'logged-out': {
    selectedAppearance: '深色',
    translationSource: '英文',
    translationTarget: '繁體中文',
    selectedLanguage: '繁體中文',
    selectedReviewMode: '已凍結 · 自訂',
    autoSyncEnabled: false,
    showAutoSync: false,
  },
}
