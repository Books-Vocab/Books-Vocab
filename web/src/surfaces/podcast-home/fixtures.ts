import type { ScenarioId } from '../../harness/scenarios'

/**
 * PodcastHomeView surface fixtures — 逐字鏡射 iOS
 * `PodcastHomeViewScenarios.swift` 的 4 個 scene（seed 合成 SwiftData store）。
 *
 * iOS scene 種子（PodcastHomeScene.seed）：
 *   palette  = ["#4A90D9","#E0719A","#3FB68B","#F2A65A","#7E6CCB"]（index % 5）
 *   patterns = [.waves,.dots,.grid,.circles,.lines]（index % 5）
 *   每 series：color/coverPattern/episodeCount/totalDurationSec/sortOrder/isFollowed。
 *   episode duration = 1500 + epIdx*332；totalDurationSec = Σ。
 *
 * 顏色：iOS `NotebookPalette.color(for:)` render-time 套 legacyMigration：
 *   #4A90D9→#AFC2D3（海洋）·#E0719A→#DEBAC2*·#3FB68B→#B7D2C9*·
 *   #F2A65A→#DEC69C**·#7E6CCB→#C5B2D0**。
 *   （* / ** 標下；migration map 來自 NotebookPalette.swift legacyMigration。
 *   #E0719A/#3FB68B/#F2A65A/#7E6CCB 不在 map 中 → `color(for:)` 直接用原 hex。
 *   實測 catalog PNG：grid card 1=藍灰(#AFC2D3 migrated)、card 2=粉紅、
 *   card 3=綠、card 4=橘，與「未在 map 內者用原 hex」一致。）
 *   故：#4A90D9 用 migrated #AFC2D3；其餘三色用原 hex（notebook palette 資料色，
 *   token-allow 豁免，非視覺 token）。
 *
 * 「繼續收聽」shelf 順序 = PodcastProgress.updatedAt 反序（最近更新在前）。
 * populated 種子插入順序：先 Atomic Ep2(612s)，後 Finding Flow Ep1(1700s)，
 * 最後 Deep Work Ep1(completed→過濾)。後插者 updatedAt 較晚 → Finding Flow 在前。
 * catalog PNG 實測：第一張 = Finding Flow（還剩 0:00），第二張 = Atomic（還剩 20:20）。
 *
 * displayTitle = `Ep {n} · {title}`；PodcastClock.format：h>0→`h:mm:ss` 否則 `m:ss`。
 * remaining 文案 = `還剩 %@`（zh-Hant）。fraction = clamp(played/duration)。
 */

const OCEAN = '#AFC2D3' // token-allow: notebook palette data color (#4A90D9 → 海洋 migrated)
const PINK = '#E0719A' // token-allow: notebook palette data color (not in legacy map → raw)
const GREEN = '#3FB68B' // token-allow: notebook palette data color (not in legacy map → raw)
const ORANGE = '#F2A65A' // token-allow: notebook palette data color (not in legacy map → raw)

export type CoverPattern = 'waves' | 'dots' | 'grid' | 'circles' | 'lines'

/** 「繼續收聽」橫排卡（PodcastContinueRailCard，cardWidth 150）。 */
export interface ContinueItem {
  /** 真實 series id（shell 路徑導航攜帶；fixture/parity 路徑省略，不渲染、不影響 DOM）。 */
  seriesId?: string
  /** 接續播放的集數（shell 導航直開 player 用；省略則落系列首集）。 */
  epNum?: number
  /** 封面色 + 封面置中白字（= series.title） */
  coverColor: string
  coverPattern: CoverPattern
  coverName: string
  /** 卡下第一行（caption sans12 bold） */
  title: string
  /** Ep N · Title（caption2 sans11 reg） */
  episodeDisplay: string
  /** clamp(played/duration)；>0 才畫 ProgressCapsule */
  fraction: number
  /** 還剩 %@（mono10 bold）；無進度時 null */
  remaining: string | null
}

/** 所有節目 grid 卡（PodcastSeriesCard，coverHeight 210）。 */
export interface SeriesCard {
  /** 真實 series id（shell 路徑導航攜帶；fixture/parity 路徑省略，不渲染、不影響 DOM）。 */
  seriesId?: string
  coverColor: string
  coverPattern: CoverPattern
  title: string
  /** 主持人(逗號) · N 集（無主持人退回純集數） */
  hosts: string[]
  count: number
  isFollowed: boolean
}

export interface PodcastHomeFixture {
  /** 是否空狀態（empty scene） */
  empty: boolean
  /** 「繼續收聽」shelf；空陣列 → 整段不顯示、grid 不冠「所有節目」標題 */
  continueItems: ContinueItem[]
  /** 所有節目 grid（followed 排前 + star badge，同組維持 sortOrder） */
  series: SeriesCard[]
}

// --- 共用 series specs（seedCatalog；followed 排前 in-memory 穩定排序）---
// sortOrder 0..3 → followed 者(Atomic,Finding Flow)浮前，其餘維持原序。
const CATALOG_SERIES: SeriesCard[] = [
  // followed=true → 排前
  {
    coverColor: OCEAN,
    coverPattern: 'waves',
    title: 'Atomic Habits Unpacked',
    hosts: ['Ava Chen'],
    count: 3,
    isFollowed: true,
  },
  {
    coverColor: PINK,
    coverPattern: 'dots',
    title: 'Finding Flow: The Science of Optimal Experience',
    hosts: ['Mihaly Csikszentmihalyi', 'Alexandra Featherstone'],
    count: 2,
    isFollowed: true,
  },
  // followed=false → 維持 sortOrder
  {
    coverColor: GREEN,
    coverPattern: 'grid',
    title: 'Deep Work in a Distracted World',
    hosts: ['Leo Park'],
    count: 4,
    isFollowed: false,
  },
  {
    coverColor: ORANGE,
    coverPattern: 'circles',
    title: 'Hidden Hand',
    hosts: ['Maya Lin'],
    count: 2,
    isFollowed: false,
  },
]

export const PODCAST_HOME_FIXTURES: Record<ScenarioId<'podcast-home'>, PodcastHomeFixture> = {
  // Content / Populated — 4 series + 2 continue（Finding Flow 在前，updatedAt 反序）
  populated: {
    empty: false,
    continueItems: [
      // all[1].1[0] = Finding Flow Ep1「What Is Flow」played 1700 / dur 1500 →
      //   fraction clamp(1700/1500)=1；remaining max(0,1500-1700)=0 → 0:00
      {
        coverColor: PINK,
        coverPattern: 'dots',
        coverName: 'Finding Flow: The Science of Optimal Experience',
        title: 'Finding Flow: The Science of Optimal Experience',
        episodeDisplay: 'Ep 1 · What Is Flow',
        fraction: 1,
        remaining: '還剩 0:00',
      },
      // all[0].1[1] = Atomic Ep2「Identity-Based Habits」played 612 / dur 1832 →
      //   fraction 612/1832；remaining 1220 → 20:20
      {
        coverColor: OCEAN,
        coverPattern: 'waves',
        coverName: 'Atomic Habits Unpacked',
        title: 'Atomic Habits Unpacked',
        episodeDisplay: 'Ep 2 · Identity-Based Habits',
        fraction: 612 / 1832,
        remaining: '還剩 20:20',
      },
    ],
    series: CATALOG_SERIES,
  },

  // Content / No continue shelf — seedCatalog 但無 PodcastProgress → grid only
  'no-continue': {
    empty: false,
    continueItems: [],
    series: CATALOG_SERIES,
  },

  // Content / Single series — 一本 Atomic（followed），progress 在 Ep2 612s
  single: {
    empty: false,
    continueItems: [
      {
        coverColor: OCEAN,
        coverPattern: 'waves',
        coverName: 'Atomic Habits Unpacked',
        title: 'Atomic Habits Unpacked',
        episodeDisplay: 'Ep 2 · Identity-Based Habits',
        fraction: 612 / 1832,
        remaining: '還剩 20:20',
      },
    ],
    series: [
      {
        coverColor: OCEAN,
        coverPattern: 'waves',
        title: 'Atomic Habits Unpacked',
        hosts: ['Ava Chen'],
        count: 3,
        isFollowed: true,
      },
    ],
  },

  // Empty — 空 store
  empty: {
    empty: true,
    continueItems: [],
    series: [],
  },
}

/** `主持人 · N 集`（無主持人退回純集數）。 */
export function metaLine(s: SeriesCard): string {
  const count = `${s.count} 集`
  const hosts = s.hosts.join(', ')
  return hosts ? `${hosts} · ${count}` : count
}
