import type { ScenarioId } from '../../harness/scenarios'

/**
 * Archived Vocab fixtures — 逐字對齊 iOS
 * `ArchivedVocabScenarios.swift` 的 `ArchivedVocabFixtures`。
 *
 * 每筆 = `archived(word, translation, partOfSpeech)`，封存態（showsArchiveStyle）
 * 只取 word / partOfSpeech / translation（showsSourceContext:false →
 * 不顯示 bookTitle/chapter；showsReviewState:false → 無 status）。
 *
 * ArchivedVocabSheet 以 `@Query(sort: \VocabularyEntry.word)` 排序（字母序），
 * 再過 `shouldAppearInArchiveList`（synced && !delete && archived，fixtures 全符合）。
 * 故 row 順序 = word 升冪（與 ref PNG 一致）。
 */

export interface ArchivedVocabRow {
  /** 顯示用 id（穩定 key） */
  id: string
  word: string
  partOfSpeech: string | null
  translation: string
}

export interface ArchivedVocabFixture {
  rows: ArchivedVocabRow[]
}

function row(word: string, translation: string, partOfSpeech: string | null = 'n.'): ArchivedVocabRow {
  return { id: word, word, partOfSpeech, translation }
}

/** word 升冪排序（mirror iOS @Query sort: \.word，String 預設比較） */
function sortByWord(rows: ArchivedVocabRow[]): ArchivedVocabRow[] {
  return [...rows].sort((a, b) => (a.word < b.word ? -1 : a.word > b.word ? 1 : 0))
}

// ArchivedVocabFixtures.single
const single: ArchivedVocabRow[] = [row('serendipity', '機緣巧合')]

// ArchivedVocabFixtures.populated（5 筆，n./adj. 混合）
const populated: ArchivedVocabRow[] = sortByWord([
  row('serendipity', '機緣巧合'),
  row('ephemeral', '短暫的', 'adj.'),
  row('petrichor', '雨後泥土香'),
  row('ineffable', '難以言喻的', 'adj.'),
  row('quintessential', '典型的', 'adj.'),
])

// ArchivedVocabFixtures.long（(1...40) → "archived-word-N" / "封存單字 N"，全 n.）
const long: ArchivedVocabRow[] = sortByWord(
  Array.from({ length: 40 }, (_, i) => {
    const idx = i + 1
    return row(`archived-word-${idx}`, `封存單字 ${idx}`)
  }),
)

export const ARCHIVED_VOCAB_FIXTURES: Record<ScenarioId<'archived-vocab'>, ArchivedVocabFixture> = {
  populated: { rows: populated },
  'single-card': { rows: single },
  empty: { rows: [] },
  'long-list': { rows: long },
}
