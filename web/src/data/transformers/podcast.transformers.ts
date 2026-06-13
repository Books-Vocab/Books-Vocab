// Pure transformers: podcast seed → API-response shapes. Series summary / detail
// are opaque RootModel dicts on the backend; we shape them to mirror the
// producer JSON the legacy mock emitted.

import type {
  PodcastProgressListResponse,
  PodcastSeriesDetail,
  PodcastSeriesSummary,
} from '../../api/types'
import type { PodcastProgressSeed, PodcastSeriesSeed } from '../seeds/podcast.seed'

export function toPodcastSeriesSummary(s: PodcastSeriesSeed): PodcastSeriesSummary {
  return {
    id: s.id,
    title: s.title,
    author: s.author,
    episode_count: s.episodeCount,
  }
}

export function toPodcastSeriesSummaries(seeds: PodcastSeriesSeed[]): PodcastSeriesSummary[] {
  return seeds.map(toPodcastSeriesSummary)
}

export function toPodcastSeriesDetail(s: PodcastSeriesSeed): PodcastSeriesDetail {
  return {
    id: s.id,
    title: s.title,
    author: s.author,
    episodes: s.episodes.map((e) => ({
      ep_num: e.epNum,
      title: e.title,
      duration_sec: e.durationSec,
    })),
  }
}

export function toPodcastProgressList(seeds: PodcastProgressSeed[]): PodcastProgressListResponse {
  return {
    items: seeds.map((p) => ({
      series_id: p.seriesId,
      ep_num: p.epNum,
      position_sec: p.positionSec,
      duration_sec: p.durationSec,
      updated_at: p.updatedAt,
    })),
  }
}
