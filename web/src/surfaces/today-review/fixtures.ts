import type { ScenarioId } from '../../harness/scenarios'

/**
 * Today Review surface fixtures — mirrors iOS Catalog "Today Review"
 * (TodayReviewScenarios.swift + TodayReviewFixtures.swift seed). 每個 scenario
 * 都是 3/12 進度的 session（忘記 1 / 記得 2），currentCard = meticulous
 * （recognition）或 ubiquitous（production）。reveal 階段（front/back）決定
 * 卡是否摺頁展開答案。
 *
 * iOS SoT 對應：
 * - recognition front：mono 大字單字 + 詞性 + 「點一下展開」hint
 * - recognition back：摺到頂的 front + 展開答案卡（serif 翻譯 + 連結 + 例句 + 釋義）
 * - production front：muted serif 翻譯 + cloze 例句（目標詞遮蔽為 ______）
 * - production back：摺到頂的 front + 展開答案卡（mono 英文單字 + 連結 + 例句 + 釋義）
 */

export type ReviewMode = 'recognition' | 'production'
export type RevealStage = 'front' | 'back'

export interface ReviewLink {
  /** 連結群組標籤（iOS group.label.localized；catalog seed 全 "相關"）。 */
  label: string
  /** 顯示的目標詞（mono emphasis）。 */
  words: string[]
  /** +N 溢出計數（iOS overflowCount，shares_usage 取前 2）。 */
  overflowCount: number
}

/** 例句的富文本片段：plain 文字 + 標記詞（highlight）。 */
export interface ExampleSegment {
  text: string
  /** 標記詞（iOS highlightMark 底色 + 斜體加重）。cloze front 用 blank。 */
  mark?: boolean
  /** production front 的遮蔽空格（iOS cloze ______）。 */
  blank?: boolean
}

export interface ReviewCard {
  mode: ReviewMode
  /** 英文單字（recognition front / production back 顯示）。 */
  word: string
  /** L1 翻譯（recognition back / production front 顯示）。 */
  translation: string
  /** 詞性 adj./n. — 接在 front prompt 後（tertiary）。 */
  partOfSpeech: string | null
  /** 難度標籤（answer 卡右上，warning 色）。null = 不顯示。 */
  difficultyTier: string | null
  /** 連結群組（answer 卡 link strip）。 */
  links: ReviewLink[]
  /** answer 卡例句（富文本片段）。 */
  exampleBack: ExampleSegment[]
  /** production front 的 cloze 例句（目標詞 → blank）。 */
  exampleFront: ExampleSegment[]
  /** answer 卡釋義段落（zh）。 */
  explanation: string
}

export interface TodayReviewFixture {
  /** 進度膠囊文字（iOS progressText）。 */
  progressText: string
  reveal: RevealStage
  forgotCount: number
  rememberedCount: number
  card: ReviewCard
}

const RECOGNITION_CARD: ReviewCard = {
  mode: 'recognition',
  word: 'meticulous',
  translation: '一絲不苟的；非常仔細的',
  partOfSpeech: 'adj.',
  difficultyTier: 'advanced',
  links: [{ label: '相關', words: ['precise', 'thorough'], overflowCount: 1 }],
  exampleBack: [
    { text: 'The editor was ' },
    { text: 'meticulous', mark: true },
    { text: ' about every line break and caption.' },
  ],
  exampleFront: [],
  explanation: '描述做事非常細心、注意細節，通常帶有正面稱讚意味。',
}

const PRODUCTION_CARD: ReviewCard = {
  mode: 'production',
  word: 'ubiquitous',
  translation: '無所不在的；普遍存在的',
  partOfSpeech: 'adj.',
  difficultyTier: 'intermediate',
  links: [{ label: '相關', words: ['pervasive', 'omnipresent'], overflowCount: 0 }],
  exampleBack: [
    { text: 'In coastal towns the smell of salt is ' },
    { text: 'ubiquitous', mark: true },
    { text: ', clinging to every street and stairwell.' },
  ],
  // cloze front：目標詞遮蔽為 ______（iOS CardRichTextRenderer mode: .cloze）。
  exampleFront: [
    { text: '…the smell of salt is ' },
    { blank: true, text: '______' },
    { text: ', clinging to every street and…' },
  ],
  explanation: '形容某事物到處都有、無處不在,常用於描述科技或現象的普及。',
}

const BASE = { progressText: '3 / 12', forgotCount: 1, rememberedCount: 2 } as const

export const TODAY_REVIEW_FIXTURES: Record<ScenarioId<'today-review'>, TodayReviewFixture> = {
  front: { ...BASE, reveal: 'front', card: RECOGNITION_CARD },
  back: { ...BASE, reveal: 'back', card: RECOGNITION_CARD },
  'production-front': { ...BASE, reveal: 'front', card: PRODUCTION_CARD },
  'production-back': { ...BASE, reveal: 'back', card: PRODUCTION_CARD },
}
