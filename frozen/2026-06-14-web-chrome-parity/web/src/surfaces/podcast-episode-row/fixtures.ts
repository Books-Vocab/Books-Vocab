import type { ComponentType, SVGProps } from 'react'

type GlyphComponent = ComponentType<SVGProps<SVGSVGElement> & { size?: number; strokeWidth?: number }>

/** trailing 配件種類 → glyph + 色 token（見 PodcastEpisodeRow.trailingAccessory）。 */
export type Accessory = 'play' | 'completed' | 'locked' | 'unavailable'

export interface EpisodeFixture {
  title: string
  episodeNumber: number
  /** createdAt 為 today → formatDate 回 "今天"。 */
  date: string
  /** durationSec 932 → formatDuration "15:32"。 */
  duration: string
  subtitleAvailable: boolean
  /** audioAvailable=false → 標題降為 tertiaryText（"Pending Upload"）。 */
  audioAvailable: boolean
  /** hasProgress（未完成且 lastPlayedTime>0）→ 顯示 ProgressCapsule。 */
  progressFraction?: number
  accessory: Accessory
}

/**
 * Podcast · Episode Row — "Variants" scene（PodcastPlayerScenarios.episodeRowStack）。
 * 5 列 PodcastEpisodeRow，durationSec 皆 932（15:32）、createdAt today（今天）：
 *   ep1 plain                       → play / accent，subtitle bubble
 *   ep2 progress(lastPlayed 410)    → play / accent，subtitle，ProgressCapsule 410/932≈0.44
 *   ep3 completed                   → checkmark / success，subtitle
 *   ep4 locked                      → lock / tertiaryText，subtitle
 *   ep5 audio=false subtitle=false  → icloud.slash / quaternaryText，標題 tertiaryText
 */
export const PODCAST_EPISODE_ROW_FIXTURES: EpisodeFixture[] = [
  {
    title: 'The Comfort Crisis',
    episodeNumber: 1,
    date: '今天',
    duration: '15:32',
    subtitleAvailable: true,
    audioAvailable: true,
    accessory: 'play',
  },
  {
    title: 'On Deep Work and Attention',
    episodeNumber: 2,
    date: '今天',
    duration: '15:32',
    subtitleAvailable: true,
    audioAvailable: true,
    progressFraction: 410 / 932,
    accessory: 'play',
  },
  {
    title: 'Habits That Compound',
    episodeNumber: 3,
    date: '今天',
    duration: '15:32',
    subtitleAvailable: true,
    audioAvailable: true,
    accessory: 'completed',
  },
  {
    title: 'Members-only Deep Dive',
    episodeNumber: 4,
    date: '今天',
    duration: '15:32',
    subtitleAvailable: true,
    audioAvailable: true,
    accessory: 'locked',
  },
  {
    title: 'Pending Upload',
    episodeNumber: 5,
    date: '今天',
    duration: '15:32',
    subtitleAvailable: false,
    audioAvailable: false,
    accessory: 'unavailable',
  },
]

export type { GlyphComponent }
