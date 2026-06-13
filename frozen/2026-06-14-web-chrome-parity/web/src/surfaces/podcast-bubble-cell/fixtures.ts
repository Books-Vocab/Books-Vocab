import type { ScenarioId } from '../../harness/scenarios'

/**
 * PodcastBubbleCell scenario fixtures — 對齊
 * PodcastSentenceCellsScenarios.swift「Podcast · Bubble Cell」4 態。
 *
 * 共用句子（BubbleCellScene fixture，id:0）：
 *   "Are you comfortable with the question I asked?"
 * 逐詞切分 → ["Are","you","comfortable","with","the","question","I","asked?"]
 *
 * 狀態旗標（驅動 active / dim 與對齊 / vocab 高亮）：
 * - active = isHighlighted（catalog 無 selection），影響：
 *     speaker tint opacity 0.88 vs 0.58；bubble bg tint 0.18 vs 0.08；
 *     文字色 primaryText vs secondaryText；border tint 0.22/1px vs 0.08/0.8px。
 * - alignRight → slot 1（Jordan, tint=success/green）並靠右；否則 slot 0（Alex,
 *     tint=accent/blue）靠左。
 * - vocabIndices → 命中詞用 paper 螢光筆底色帶（line bottom 32%、word width+4）。
 */
type Word = { text: string; vocab: boolean }

const SENTENCE = ['Are', 'you', 'comfortable', 'with', 'the', 'question', 'I', 'asked?']

function words(vocab: Set<number> = new Set()): Word[] {
  return SENTENCE.map((text, i) => ({ text, vocab: vocab.has(i) }))
}

export type BubbleCellFixture = {
  speaker: string
  /** slot 0 = accent(Alex)，slot 1 = success(Jordan) */
  slot: 0 | 1
  active: boolean
  alignRight: boolean
  words: Word[]
}

export const PODCAST_BUBBLE_CELL_FIXTURES: Record<ScenarioId<'podcast-bubble-cell'>, BubbleCellFixture> = {
  // BubbleCellScene(isCurrent:true, isHighlighted:true) — Alex slot0, active
  'highlighted-active': {
    speaker: 'Alex',
    slot: 0,
    active: true,
    alignRight: false,
    words: words(),
  },
  // BubbleCellScene(isCurrent:false, isHighlighted:false) — Alex slot0, dim
  'idle-non-current': {
    speaker: 'Alex',
    slot: 0,
    active: false,
    alignRight: false,
    words: words(),
  },
  // BubbleCellScene(..., alignRight:true) — Jordan slot1, dim, 靠右
  'right-aligned-speaker': {
    speaker: 'Jordan',
    slot: 1,
    active: false,
    alignRight: true,
    words: words(),
  },
  // BubbleCellScene(..., vocabIndices:[0,2]) — Alex slot0, dim, 詞0/2 螢光
  'vocab-highlighted': {
    speaker: 'Alex',
    slot: 0,
    active: false,
    alignRight: false,
    words: words(new Set([0, 2])),
  },
}
