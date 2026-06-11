import type { ScenarioId } from '../../harness/scenarios'

/**
 * Vocabulary surface fixtures — mirrors iOS Catalog "Vocabulary List View"
 * (ios/BooksAndVocab/Debug/Scenarios/VocabularyListViewScenarios.swift seed).
 *
 * 該 surface = `VocabularyListView`：large nav title「我的單字本」+ search field +
 * 三態 stat segment（未學習/待複習/已複習）+ chip/sort 列（sort pill + 未學複習
 * CTA pill）+ VocabListCard 包住的 KGVocabRow 列表。
 *
 * Seed 全是 freshly-added 未學卡（`synced(...)` helper）：syncStatus=synced、
 * isArchived=false、actionType=add，且皆 unlearned（reviewState=.unlearned）→
 * 每張卡右側顯示 detailLabel「首輪 12h」（reviewIntervalHours.compactHourLabel，
 * ratio=nil → 無進度條只有文字；見 WordRowPresentation.reviewProgressData）。
 * 因此三態 segment 的 unlearned = 卡數、due/reviewed = 0；CTA pill 數字 = unlearned。
 *
 * pendingAdd entry（syncStatus=pending）在 iOS 進 allEntries 驅動 toolbar pending
 * badge，但被 knowledgeListPredicate（syncStatus==synced）濾出 knowledge list →
 * 不進 row 列表、不計入三態 segment。故 populated 的第五筆 quintessential 不出現
 * 在 web 列表（與 catalog PNG 一致：只 4 row）。
 */

export interface VocabRowFixture {
  /** mono 18 bold 單字。 */
  word: string
  /** 詞性 caption（n. / adj.）。 */
  partOfSpeech: string
  /** body 17 secondary 翻譯。 */
  translation: string
  /** 右側 monoLabel detailLabel（unlearned seed 皆「首輪 12h」）。 */
  detail: string
}

export interface VocabFixture {
  /** 三態 segment 計數。 */
  stats: { unlearned: number; due: number; reviewed: number }
  /** chip/sort 列尾端「未學複習」CTA pill 數字；0 ⇒ 不顯示（empty 時）。 */
  ctaCount: number
  rows: VocabRowFixture[]
  /** rows 為空時的 in-card empty state（empty · zero data 走 hasNoEntries CTA）。 */
  empty?: {
    title: string
    description: string
    /** zero-data CTA 按鈕文案；undefined ⇒ guidanceText fallback（搜尋/篩選空狀態）。 */
    actionTitle?: string
    /** SF symbol 語意：'books'（zero-data）或 'search'（no-match）。 */
    icon: 'books' | 'search'
  }
}

/** 未學卡 detailLabel：reviewIntervalHours 預設 12h → compactHourLabel = "12h"。 */
const FIRST_ROUND = '首輪 12h'

function unlearned(word: string, partOfSpeech: string, translation: string): VocabRowFixture {
  return { word, partOfSpeech, translation, detail: FIRST_ROUND }
}

// VocabularyListViewFixtures.populated 的 synced 子集（pendingAdd quintessential
// 不進 knowledge list）→ 4 row，皆 unlearned。
const POPULATED_ROWS: VocabRowFixture[] = [
  unlearned('serendipity', 'n.', '機緣巧合'),
  unlearned('ephemeral', 'adj.', '短暫的'),
  unlearned('petrichor', 'n.', '雨後泥土香'),
  unlearned('ineffable', 'adj.', '難以言喻的'),
]

export const VOCABULARY_FIXTURES: Record<ScenarioId<'vocabulary'>, VocabFixture> = {
  // Populated · mixed sync states：4 synced unlearned row + 1 pending（不顯示）。
  // 三態 = 未學習 4 / 待複習 0 / 已複習 0；CTA「未學複習」= 4。
  populated: {
    stats: { unlearned: 4, due: 0, reviewed: 0 },
    ctaCount: 4,
    rows: POPULATED_ROWS,
  },
  // Single card：單一 unlearned。三態 = 1/0/0；CTA = 1。
  single: {
    stats: { unlearned: 1, due: 0, reviewed: 0 },
    ctaCount: 1,
    rows: [unlearned('serendipity', 'n.', '機緣巧合')],
  },
  // Empty · zero data：登入但整本 notebook 無卡 → hasNoEntries CTA「重新整理」。
  // 三態全 0；無 CTA pill（unlearned+due == 0）。
  empty: {
    stats: { unlearned: 0, due: 0, reviewed: 0 },
    ctaCount: 0,
    rows: [],
    empty: {
      title: '尚無已收錄單字',
      description: '在書架閱讀時長按生字加入單字本，或重新整理以拉取雲端已有資料。',
      actionTitle: '重新整理',
      icon: 'books',
    },
  },
}
