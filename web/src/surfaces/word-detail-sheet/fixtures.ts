import type { ScenarioId } from '../../harness/scenarios'

/**
 * WordDetailSheet fixtures — 逐字對齊 iOS `WordDetailScenarios`
 * (Word Detail · Sheet)：richEntry()（"ephemeral"）與 minimalEntry()（"terse"）。
 *
 * ⚠️ catalog snapshot 實況：兩個 scene 的 ref PNG **byte-identical**（md5 相同），
 * 內容皆為 WordDetailSheet else-branch 的「載入中」placeholder
 * （VocabStateMessageCard），presenter state 在 `.task` yield 後才填充、snapshot
 * 早於 presenter 完成。故 web 渲染 placeholder（不渲染實際 entry 內容）；entry
 * 資料在此保留作 SoT 對齊紀錄與後續可能的非-loading 重拍。
 */

interface WordDetailEntry {
  word: string
  translation: string
  partOfSpeech: string
  difficultyTier: string | null
}

export const WORD_DETAIL_SHEET_FIXTURES: Record<
  ScenarioId<'word-detail-sheet'>,
  WordDetailEntry
> = {
  // richEntry()
  'rich-entry': {
    word: 'ephemeral',
    translation: '短暫的；轉瞬即逝的',
    partOfSpeech: 'adj.',
    difficultyTier: 'advanced',
  },
  // minimalEntry()
  'minimal-entry': {
    word: 'terse',
    translation: '簡潔的',
    partOfSpeech: 'adj.',
    difficultyTier: null,
  },
}
