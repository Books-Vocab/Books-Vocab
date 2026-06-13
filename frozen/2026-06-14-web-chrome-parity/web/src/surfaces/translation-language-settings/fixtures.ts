import type { ScenarioId } from '../../harness/scenarios'

/**
 * TranslationLanguageSettings fixtures — 鏡像 iOS `TranslationLanguageSettingsScenarios`
 * 的 4 個 source→target 語言對。
 *
 * 語言清單 / 順序 / nativeName / flagEmoji 逐項對齊 `TranslationLanguage.swift`：
 *   sourceLanguages = [en, ja, ko, fr, de, es]
 *   targetLanguages = [zhHant, zhHans, en, ja, ko]
 * 每 scene 在 source 區選一語、target 區選一語（accent@0.08 高亮列 + 尾勾）。
 */

export interface TranslationLanguage {
  /** TranslationLanguage.id (rawValue)。 */
  id: string
  /** nativeName（語言自稱，逐字對齊 iOS）。 */
  nativeName: string
  /** flagEmoji。 */
  flag: string
}

/** TranslationLanguage.sourceLanguages — [en, ja, ko, fr, de, es]。 */
export const SOURCE_LANGUAGES: TranslationLanguage[] = [
  { id: 'en', nativeName: 'English', flag: '🇺🇸' },
  { id: 'ja', nativeName: '日本語', flag: '🇯🇵' },
  { id: 'ko', nativeName: '한국어', flag: '🇰🇷' },
  { id: 'fr', nativeName: 'Français', flag: '🇫🇷' },
  { id: 'de', nativeName: 'Deutsch', flag: '🇩🇪' },
  { id: 'es', nativeName: 'Español', flag: '🇪🇸' },
]

/** TranslationLanguage.targetLanguages — [zhHant, zhHans, en, ja, ko]。 */
export const TARGET_LANGUAGES: TranslationLanguage[] = [
  { id: 'zh-Hant', nativeName: '繁體中文', flag: '🇹🇼' },
  { id: 'zh-Hans', nativeName: '简体中文', flag: '🇨🇳' },
  { id: 'en', nativeName: 'English', flag: '🇺🇸' },
  { id: 'ja', nativeName: '日本語', flag: '🇯🇵' },
  { id: 'ko', nativeName: '한국어', flag: '🇰🇷' },
]

export interface TranslationLangFixture {
  /** 選定 source 語言 id。 */
  sourceId: string
  /** 選定 target 語言 id。 */
  targetId: string
}

export const TRANSLATION_LANG_FIXTURES: Record<
  ScenarioId<'translation-language-settings'>,
  TranslationLangFixture
> = {
  'english-to-traditional-chinese': { sourceId: 'en', targetId: 'zh-Hant' },
  'japanese-to-english': { sourceId: 'ja', targetId: 'en' },
  'french-to-simplified-chinese': { sourceId: 'fr', targetId: 'zh-Hans' },
  'korean-to-japanese': { sourceId: 'ko', targetId: 'ja' },
}
