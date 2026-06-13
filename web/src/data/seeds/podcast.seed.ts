// Podcast domain seed — editorial series catalog, episodes, user progress, and
// the demo subtitle track. Lifted verbatim from the legacy api/mock/data.ts
// (MOCK_PODCAST_SERIES / MOCK_PODCAST_DETAIL / MOCK_PODCAST_PROGRESS /
// MOCK_SUBTITLE_SRT).

import { SEED_NOW_ISO } from './account.seed'

export interface PodcastEpisodeSeed {
  epNum: number
  title: string
  durationSec: number
}

export interface PodcastSeriesSeed {
  id: string
  title: string
  author: string
  /** Total episode count advertised in the series summary. */
  episodeCount: number
  /** Episodes carried in the series detail payload. */
  episodes: PodcastEpisodeSeed[]
}

export const PODCAST_SERIES_SEEDS: PodcastSeriesSeed[] = [
  {
    id: 'pride-and-prejudice',
    title: 'Pride and Prejudice',
    author: 'Jane Austen',
    episodeCount: 6,
    episodes: [
      { epNum: 1, title: 'Chapter 1', durationSec: 1832 },
      { epNum: 2, title: 'Chapter 2', durationSec: 1740 },
    ],
  },
]

export interface PodcastProgressSeed {
  seriesId: string
  epNum: number
  positionSec: number
  durationSec: number
  updatedAt: string
}

export const PODCAST_PROGRESS_SEEDS: PodcastProgressSeed[] = [
  { seriesId: 'pride-and-prejudice', epNum: 1, positionSec: 6.09, durationSec: 1832, updatedAt: SEED_NOW_ISO },
]

/** Raw SRT for GET /api/podcasts/{series}/{ep}/subtitle (text/plain). */
export const PODCAST_SUBTITLE_SRT = `1
00:00:00,000 --> 00:00:02,500
It is a truth universally acknowledged,

2
00:00:02,500 --> 00:00:05,000
that a single man in possession of a good fortune,
`
