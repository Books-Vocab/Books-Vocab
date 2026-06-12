import type { ScenarioId } from '../../harness/scenarios'

/**
 * PodcastSeriesCard surface fixtures — 鏡射 iOS PodcastShelfCardsScenarios.swift
 * 的 `PodcastSeriesCardScene`（poster-style series tile）。catalog 不掛 SwiftData，
 * 故直接餵合成 PodcastSeries 資料。
 *
 * 注意 cover 顏色：iOS scene 設 `series.color = "#4A90D9"`，但 NotebookPalette
 * legacy migration 在 render-time 把 `#4A90D9` → `#AFC2D3`（海洋 Morandi），
 * catalog PNG 實測即此藍灰。fixture 直接給 migrated hex（NotebookPalette data
 * color，iOS 端亦 token-allow）。
 *
 * width：default 160pt，Narrow 120pt（iOS `.frame(width:)`）。
 * meta：`主持人(逗號連接) · N 集`，單行 tail 截斷。
 */

export interface PodcastSeriesCardFixture {
  /** 封面色（NotebookPalette migrated hex） */
  coverColor: string
  /** series.title（封面置中白字 + 卡下標題，標題 lineLimit(2) reservesSpace） */
  title: string
  /** 主持人名（逗號連接後接 ` · N 集`） */
  hosts: string[]
  /** episodeCount */
  count: number
  /** 卡寬（pt → px，preview dpr3 截圖） */
  width: number
}

const OCEAN = '#AFC2D3' // #4A90D9 → legacy-migrated（NotebookPalette）

export const PODCAST_SERIES_CARD_FIXTURES: Record<
  ScenarioId<'podcast-series-card'>,
  PodcastSeriesCardFixture
> = {
  normal: {
    coverColor: OCEAN,
    title: 'Atomic Habits Unpacked',
    hosts: ['Ava Chen'],
    count: 7,
    width: 160,
  },
  'long-host': {
    coverColor: OCEAN,
    title: 'Finding Flow: The Science of Optimal Experience',
    hosts: ['Mihaly Csikszentmihalyi', 'Alexandra Penultimate-Featherstonehaugh'],
    count: 24,
    width: 160,
  },
  narrow: {
    coverColor: OCEAN,
    title: 'Let Them, Let Me',
    hosts: ['Leo Park', 'Ava Chen'],
    count: 8,
    width: 120,
  },
  a11y3: {
    coverColor: OCEAN,
    title: 'Hidden Hand',
    hosts: ['Leo Park'],
    count: 12,
    width: 160,
  },
}

/** `主持人 · N 集`（無主持人退回純集數） */
export function metaLine(f: PodcastSeriesCardFixture): string {
  const count = `${f.count} 集`
  const hosts = f.hosts.join(', ')
  return hosts ? `${hosts} · ${count}` : count
}
