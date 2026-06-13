import type { ScenarioId } from '../../harness/scenarios'

/**
 * Podcast Hero fixtures — mirror `PodcastSeriesHeroScenarios.swift`.
 *
 * meta line (`主持人 · N 集 · 共 X 小時 Y 分`) assembles conditionally in iOS
 * `PodcastSeriesHero.metaText`:
 *   - hosts.joined(", ")   if !hosts.isEmpty
 *   - "%@ 集"               if episodeCount > 0
 *   - 共 %@ 小時 %@ 分 / 共 %@ 分鐘  if totalDurationSec > 0
 * joined by " · "; nil → no meta Text rendered.
 *
 * cover color: series.color = "#4A90D9" → NotebookPalette legacyMigration →
 * "#AFC2D3" (海洋 Morandi blue-grey). This is render-time *data* color
 * (token-allow in iOS), so it lives in fixtures, not as a design token.
 * coverPattern = .waves; coverImagePath = nil → solid color + waves overlay +
 * centered white name text.
 */
export interface PodcastHeroFixture {
  title: string
  /** computed meta string, or null when no meta parts (Fresh · no meta) */
  meta: string | null
  /** dynamicTypeSize accessibility3 baseline */
  a11y3?: boolean
}

function formatDuration(sec: number): string | null {
  if (!Number.isFinite(sec) || sec <= 0) return null
  const total = Math.trunc(sec)
  const h = Math.trunc(total / 3600)
  const m = Math.trunc((total % 3600) / 60)
  if (h > 0) return `共 ${h} 小時 ${m} 分`
  return `共 ${m} 分鐘`
}

function buildMeta(hosts: string[], episodeCount: number, totalDurationSec: number): string | null {
  const parts: string[] = []
  if (hosts.length > 0) parts.push(hosts.join(', '))
  if (episodeCount > 0) parts.push(`${episodeCount} 集`)
  const dur = formatDuration(totalDurationSec)
  if (dur) parts.push(dur)
  return parts.length === 0 ? null : parts.join(' · ')
}

export const PODCAST_HERO_FIXTURES: Record<ScenarioId<'podcast-hero'>, PodcastHeroFixture> = {
  'full-meta': {
    title: 'Atomic Habits Unpacked',
    meta: buildMeta(['Ava Chen', 'Leo Park'], 7, 7 * 932),
  },
  'long-title-multi-host': {
    title: 'Finding Flow: The Science of Optimal Experience',
    meta: buildMeta(
      ['Mihaly Csikszentmihalyi', 'Alexandra Penultimate-Featherstonehaugh'],
      24,
      24 * 1840,
    ),
  },
  'fresh-no-meta': {
    title: 'The Comfort Crisis',
    meta: buildMeta([], 0, 0),
  },
  'episodes-only': {
    title: 'Hidden Hand',
    meta: buildMeta([], 3, 0),
  },
  a11y3: {
    title: 'Let Them, Let Me',
    meta: buildMeta(['Leo Park', 'Ava Chen'], 12, 12 * 1205),
    a11y3: true,
  },
}

/** cover data color: #4A90D9 → legacyMigration → #AFC2D3 (海洋) */
export const HERO_COVER_COLOR = '#AFC2D3'
