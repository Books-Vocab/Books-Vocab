// "Continue listening" shelf derivation — web mirror of iOS PodcastHomeView's
// `continueShelf` (PodcastProgress joined cross-series by updatedAt desc).
// Pure functions, no DOM, no React.
//
// Source: GET /api/podcasts/progress (PodcastProgressListResponse). Each row
// carries series_id / ep_num / position_sec / duration_sec / updated_at. We join
// against the editorial series catalog (opaque dicts) to recover the human title
// and episode title, then sort by updated_at desc — most-recently-played first,
// exactly as the iOS `@Query PodcastProgress(updatedAt desc)` does.
//
// A completed episode (position >= duration) is filtered out (iOS hides finished
// rows from the continue shelf — you continue what's unfinished).

import type {
  PodcastProgressListResponse,
  PodcastProgressResponse,
  PodcastSeriesSummary,
} from '../../api/types'
import { formatClock } from './timeline'

/** One resolved continue-shelf row, ready for PodcastContinueRailCard. */
export interface ContinueShelfItem {
  seriesId: string
  epNum: number
  /** series.title (falls back to series_id when the catalog lacks it). */
  seriesTitle: string
  /** `Ep N · {episode title}` (episode title omitted when unknown). */
  episodeDisplay: string
  /** clamp(position/duration) in [0,1]. */
  fraction: number
  /** `還剩 m:ss` remaining clock; null when duration is unknown. */
  remaining: string | null
  /** ISO8601 from the progress row (sort key). */
  updatedAt: string
}

function str(v: unknown): string | undefined {
  return typeof v === 'string' && v.length > 0 ? v : undefined
}

/** Pull a series' display title from an opaque catalog dict. */
function seriesTitleOf(series: PodcastSeriesSummary | undefined, seriesId: string): string {
  return str(series?.title) ?? seriesId
}

/** Pull an episode title from a series' opaque `episodes` array, by ep_num. */
function episodeTitleOf(series: PodcastSeriesSummary | undefined, epNum: number): string | undefined {
  const eps = series?.episodes
  if (!Array.isArray(eps)) return undefined
  for (const e of eps) {
    if (e && typeof e === 'object' && Number((e as Record<string, unknown>).ep_num) === epNum) {
      return str((e as Record<string, unknown>).title)
    }
  }
  return undefined
}

function clamp01(v: number): number {
  if (!Number.isFinite(v)) return 0
  return v < 0 ? 0 : v > 1 ? 1 : v
}

/** True when the row is finished (no longer "continue"). */
export function isCompleted(p: PodcastProgressResponse): boolean {
  return p.duration_sec > 0 && p.position_sec >= p.duration_sec
}

/**
 * Build the continue shelf: drop completed rows, join titles, sort by
 * updated_at desc (ISO8601 strings sort lexicographically = chronologically).
 * `catalog` is keyed by series id; missing entries degrade gracefully to the id.
 */
export function buildContinueShelf(
  progress: PodcastProgressListResponse,
  catalog: Map<string, PodcastSeriesSummary>,
): ContinueShelfItem[] {
  return progress.items
    .filter((p) => !isCompleted(p))
    .map((p): ContinueShelfItem => {
      const series = catalog.get(p.series_id)
      const epTitle = episodeTitleOf(series, p.ep_num)
      const fraction = clamp01(p.duration_sec > 0 ? p.position_sec / p.duration_sec : 0)
      const remainingSec = p.duration_sec > 0 ? Math.max(0, p.duration_sec - p.position_sec) : null
      return {
        seriesId: p.series_id,
        epNum: p.ep_num,
        seriesTitle: seriesTitleOf(series, p.series_id),
        episodeDisplay: epTitle ? `Ep ${p.ep_num} · ${epTitle}` : `Ep ${p.ep_num}`,
        fraction,
        remaining: remainingSec == null ? null : `還剩 ${formatClock(remainingSec)}`,
        updatedAt: p.updated_at,
      }
    })
    .sort((a, b) => (a.updatedAt < b.updatedAt ? 1 : a.updatedAt > b.updatedAt ? -1 : 0))
}

/** Convenience: index a series catalog list into an id→summary map. */
export function indexCatalog(series: PodcastSeriesSummary[]): Map<string, PodcastSeriesSummary> {
  const map = new Map<string, PodcastSeriesSummary>()
  for (const s of series) {
    const id = str(s.id)
    if (id) map.set(id, s)
  }
  return map
}
