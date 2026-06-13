import type { ScenarioId } from '../../harness/scenarios'

/**
 * PodcastContinueCard fixtures — iOS `PodcastContinueCardScenarios.swift` 的
 * 鏡像。每個 scenario 餵一個 (action × episode × progress) 投影，驅動 disc
 * icon、eyebrow 動詞、displayTitle、進度膠囊 + 還剩時間、trailing chevron/lock。
 *
 * Gated scenario 在 catalog 是 `PodcastContinueCardGatedScene`：三張卡堆疊
 * (signIn / upgrade / unavailable)，用 cards 陣列表達。
 */

export type DiscIcon = 'play' | 'lock' | 'person' | 'icloud-slash'

export interface ContinueCard {
  /** disc 圖示（discIcon switch on action） */
  disc: DiscIcon
  /** isActionable = action != .unavailable（驅動 disc 填色 / 文字色） */
  actionable: boolean
  /** eyebrow 動詞（caption, sans12 bold） */
  eyebrow: string
  /** episode.displayTitle = "Ep N · title"（sectionTitle serif18 bold） */
  title: string
  /** navigatesToPlayer → chevron.right，否則 lock.fill */
  navigatesToPlayer: boolean
  /** in-progress resume 才 > 0；驅動進度膠囊（accent fill, h3） */
  progressFraction: number
  /** resume 才有；mono10 還剩 m:ss */
  remaining: string | null
}

export const PODCAST_CONTINUE_CARD_FIXTURES: Record<
  ScenarioId<'podcast-continue-card'>,
  { cards: ContinueCard[] }
> = {
  'in-progress': {
    cards: [
      {
        disc: 'play',
        actionable: true,
        eyebrow: '繼續播放',
        // ep2, durationSec 932, lastPlayed 410 → 410/932 ≈ 0.4399, 還剩 522s = 8:42
        title: 'Ep 2 · On Deep Work and Attention',
        navigatesToPlayer: true,
        progressFraction: 410 / 932,
        remaining: '還剩 8:42',
      },
    ],
  },
  fresh: {
    cards: [
      {
        disc: 'play',
        actionable: true,
        eyebrow: '開始播放',
        title: 'Ep 1 · The Comfort Crisis',
        navigatesToPlayer: true,
        progressFraction: 0,
        remaining: null,
      },
    ],
  },
  completed: {
    cards: [
      {
        disc: 'play',
        actionable: true,
        eyebrow: '重新播放',
        title: 'Ep 1 · The Comfort Crisis',
        navigatesToPlayer: true,
        progressFraction: 0,
        remaining: null,
      },
    ],
  },
  'free-preview': {
    cards: [
      {
        disc: 'play',
        actionable: true,
        eyebrow: '免費試聽 3 分鐘',
        title: 'Ep 1 · The Comfort Crisis',
        navigatesToPlayer: true,
        progressFraction: 0,
        remaining: null,
      },
    ],
  },
  gated: {
    cards: [
      {
        disc: 'person',
        actionable: true,
        eyebrow: '登入後收聽',
        title: 'Ep 1 · The Comfort Crisis',
        navigatesToPlayer: false,
        progressFraction: 0,
        remaining: null,
      },
      {
        disc: 'lock',
        actionable: true,
        eyebrow: '升級 Pro',
        title: 'Ep 3 · Habits That Compound',
        navigatesToPlayer: false,
        progressFraction: 0,
        remaining: null,
      },
      {
        disc: 'icloud-slash',
        actionable: false,
        eyebrow: '音訊暫不可用',
        title: 'Ep 4 · Pending Upload',
        navigatesToPlayer: false,
        progressFraction: 0,
        remaining: null,
      },
    ],
  },
}
