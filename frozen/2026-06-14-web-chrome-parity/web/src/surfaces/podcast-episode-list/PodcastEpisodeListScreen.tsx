import { useCallback, useEffect, useMemo, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import { useApi } from '../../api/ApiContext'
import type { PodcastSeriesDetail } from '../../api/types'
import {
  COVER_COLOR,
  PODCAST_EPISODE_LIST_FIXTURES,
  type EpisodeFixture,
  type PodcastEpisodeListFixture,
} from './fixtures'
import { ChevronDownIcon, LockFillIcon, WaveformSlashIcon } from './icons'
import { useShellNav } from '../../shell/ShellNavContext'
import { pushTargetFor, screenFor } from '../../shell/nav'
import { PodcastNowPlaying } from '../podcast/PodcastNowPlaying'
import './podcast-episode-list.css'

/**
 * Podcast Episode List — iOS `PodcastEpisodeListView`（Views/Podcast/）的 web 鏡像。
 *
 * Scene（PodcastEpisodeListViewScenarios, layout=.fill，alpha-mean=1 不透明）：
 *   NavigationStack[ PodcastEpisodeListView ]
 *     .navigationTitle(series.title) .navigationBarTitleDisplayMode(.inline)
 *   inline nav title 在 catalog 以極淡 chrome 渲染（量測 ≈252 on 247 頁底色，近隱形）
 *   → token-allow 淡灰近似（對齊 archived-vocab / notebook-edit 策略）。nav band
 *     bottom ≈ 340px native ≈ 113pt（hero backdrop 起點實測）。
 *
 * body = VocabSceneShell(phase) { ScrollView { LazyVStack(spacing sectionGap=14)[
 *   heroHeader · staleDataBanner · episodesSection ]
 *   .padding(.horizontal cardPadding=18).padding(.bottom sheetSectionSpacing) }
 *   .background(pageBackground) }
 *
 * populated（free tier，無 Pro）：
 *   heroHeader = VStack(spacing statusHeroGap=12)[ PodcastSeriesHero · heroContinue ]
 *     .padding(.bottom sectionGap=14)；heroContinue .padding(.top inlineGap=8)
 *   PodcastSeriesHero：backdrop band(196) + 浮置 cover(136) + title(displayTitle
 *     serif24 bold) + meta(caption sans12 bold / tertiary)「Ava Chen, Leo Park」
 *   heroContinue → PodcastContinueCard(action .upgrade)：lock disc on brandHero +
 *     eyebrow「升級 Pro」 + title「Ep 1 · The Comfort Crisis」 + trailing lock
 *   episodesSection：HStack[ Text「集數」(sectionTitle) · Spacer · sortMenu ]
 *     .padding(.h microGap=6) ＋ ListSectionCard{ 4 × PodcastEpisodeRow + Divider }
 *   每集 row：title(serif18 bold) + meta「Ep N · 今天 · M:SS」(monoLabel mono10 bold) +
 *     trailing lock.fill（全集 locked）。
 *
 * empty：VocabSceneShell .empty → VStack[Spacer · VocabEmptyStateCard · Spacer]
 *   .padding(cardBlockPadding)；card = AppSectionCard(.vocab)：白底 + cardBorder×0.7
 *   1px + radius card=8 + z1，內含 waveform.slash(symbolLarge 30) +「尚無集數」
 *   (sectionTitle serif18 bold) +「此系列目前沒有可播放的集數」(body sans17 / secondary)。
 */

export function PodcastEpisodeListScreen({
  scenario,
}: {
  scenario: ScenarioId<'podcast-episode-list'>
}) {
  const shell = new URLSearchParams(window.location.search).get('shell') === '1'
  if (shell) {
    return <PodcastEpisodeListScreenApi />
  }
  return <PodcastEpisodeListScreenFixture scenario={scenario} />
}

function PodcastEpisodeListScreenFixture({ scenario }: { scenario: ScenarioId<'podcast-episode-list'> }) {
  const fixture = PODCAST_EPISODE_LIST_FIXTURES[scenario]
  return <PodcastEpisodeListBody fixture={fixture} />
}

function PodcastEpisodeListScreenApi() {
  const api = useApi()
  const nav = useShellNav()
  // master-detail：seriesId 由 home 系列卡點擊攜入（ShellNavContext.params）；
  // 缺省（直接深連到此 surface）退回 catalog 首個系列，仍可達。
  const seriesId = nav.params.seriesId ?? null
  const [detail, setDetail] = useState<PodcastSeriesDetail | null>(null)
  const [resolvedSeriesId, setResolvedSeriesId] = useState<string | null>(seriesId)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      let sid = seriesId
      if (!sid) {
        const series = await api.podcast.series()
        sid = series.length > 0 && series[0].id != null ? String(series[0].id) : null
      }
      if (sid) {
        setResolvedSeriesId(sid)
        const d = await api.podcast.seriesDetail(sid)
        setDetail(d)
      }
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [api, seriesId])

  useEffect(() => {
    load()
  }, [load])

  // 點集數 row → push player（攜 seriesId + epNum）。鏡射 iOS PodcastNavRoute.episode。
  const openEpisode = (epNum: number) => {
    const sid = resolvedSeriesId ?? undefined
    const list = screenFor('podcast-episode-list', sid ? { seriesId: sid } : undefined)
    const player = pushTargetFor(
      list,
      'open-podcast-episode',
      sid ? { seriesId: sid, epNum } : { epNum },
    )
    if (player) nav.navigate(player)
  }

  const fixture = useMemo((): PodcastEpisodeListFixture => {
    if (loading || !detail) {
      return {
        navTitle: '',
        seriesTitle: '',
        meta: null,
        continueCard: null,
        sectionTitle: '集數',
        sortLabel: '集數由小到大',
        episodes: [],
        empty: { title: '尚無集數', description: '此系列目前沒有可播放的集數' },
      }
    }
    const episodes = Array.isArray(detail.episodes)
      ? detail.episodes.map((ep: unknown) => {
          const e = ep as { ep_num?: number; title?: string; duration_sec?: number }
          return {
            episodeNumber: Number(e.ep_num ?? 0),
            title: String(e.title ?? ''),
            duration: formatDuration(Number(e.duration_sec ?? 0)),
            date: '今天',
          }
        })
      : []
    const isEmpty = episodes.length === 0
    return {
      navTitle: String(detail.title ?? ''),
      seriesTitle: String(detail.title ?? ''),
      meta: String(detail.author ?? '').length > 0 ? String(detail.author ?? '') : null,
      continueCard: isEmpty
        ? null
        : {
            eyebrow: '升級 Pro',
            title: `Ep ${episodes[0].episodeNumber} · ${episodes[0].title}`,
          },
      sectionTitle: '集數',
      sortLabel: '集數由小到大',
      episodes,
      empty: isEmpty ? { title: '尚無集數', description: '此系列目前沒有可播放的集數' } : null,
    }
  }, [loading, detail])

  return (
    <>
      <PodcastEpisodeListBody fixture={fixture} onOpenEpisode={openEpisode} />
      {/* Persistent now-playing layer: keeps the mini-player alive on this
          intermediate surface during home → series → episode → player. */}
      <PodcastNowPlaying />
    </>
  )
}

function PodcastEpisodeListBody({
  fixture,
  onOpenEpisode,
}: {
  fixture: PodcastEpisodeListFixture
  /** shell 路徑：點 row → push player。parity 路徑省略 → row 非互動（DOM 不變）。 */
  onOpenEpisode?: (epNum: number) => void
}) {
  const isEmpty = fixture.episodes.length === 0

  return (
    <div className="pel-surface">
      {/* inline nav bar：status + bar ≈113pt，標題置中、極淡（catalog 渲染近隱形） */}
      <header className="pel-nav">
        <span className="pel-nav-title">{fixture.navTitle}</span>
      </header>

      {isEmpty ? (
        <EmptyBody fixture={fixture} />
      ) : (
        <ContentBody fixture={fixture} onOpenEpisode={onOpenEpisode} />
      )}
    </div>
  )
}

function ContentBody({
  fixture,
  onOpenEpisode,
}: {
  fixture: PodcastEpisodeListFixture
  onOpenEpisode?: (epNum: number) => void
}) {
  return (
    <div className="pel-scroll">
      {/* LazyVStack(spacing sectionGap=14).padding(.h cardPadding=18) */}
      <div className="pel-stack">
        {/* heroHeader = VStack(spacing statusHeroGap=12)[hero · continue].padding(.bottom sectionGap) */}
        <div className="pel-hero-header">
          <SeriesHero title={fixture.seriesTitle} meta={fixture.meta} />
          {fixture.continueCard ? (
            <div className="pel-hero-continue">
              <ContinueCard eyebrow={fixture.continueCard.eyebrow} title={fixture.continueCard.title} />
            </div>
          ) : null}
        </div>

        {/* episodesSection */}
        <section className="pel-episodes">
          <div className="pel-episodes-head">
            <span className="pel-episodes-title">{fixture.sectionTitle}</span>
            <span className="pel-sort">
              {fixture.sortLabel}
              <ChevronDownIcon className="pel-sort-chevron" size={12} />
            </span>
          </div>

          {/* ListSectionCard{ rows + dividers } */}
          <div className="pel-list-card">
            {fixture.episodes.map((ep, i) => (
              <div key={ep.episodeNumber}>
                {i > 0 ? <div className="pel-divider" /> : null}
                <EpisodeRow ep={ep} onOpen={onOpenEpisode ? () => onOpenEpisode(ep.episodeNumber) : undefined} />
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}

/** PodcastSeriesHero：backdrop band(196) + 浮置 cover(136) + title + meta。 */
function SeriesHero({ title, meta }: { title: string; meta: string | null }) {
  return (
    <div className="pel-hero">
      <div
        className="pel-hero-backdrop"
        style={{ ['--hero-cover-color' as string]: COVER_COLOR }}
      >
        <div className="pel-hero-backdrop-wash" />
        <div className="pel-hero-backdrop-fade" />
        <div className="pel-hero-cover">
          <CoverWaves />
          <div className="pel-hero-cover-name">{title}</div>
        </div>
      </div>

      <div className="pel-hero-title">{title}</div>
      {meta ? <div className="pel-hero-meta">{meta}</div> : null}
    </div>
  )
}

/** PodcastContinueCard(action .upgrade)：lock disc(brandHero) + eyebrow + title + trailing lock。 */
function ContinueCard({ eyebrow, title }: { eyebrow: string; title: string }) {
  return (
    <div className="pel-cc-card">
      <div className="pel-cc-disc">
        <LockFillIcon className="pel-cc-disc-icon" size={16} />
      </div>
      <div className="pel-cc-body">
        <div className="pel-cc-eyebrow">{eyebrow}</div>
        <div className="pel-cc-title">{title}</div>
      </div>
      <span className="pel-cc-trailing">
        <LockFillIcon size={14} />
      </span>
    </div>
  )
}

/** PodcastEpisodeRow（locked 變體）：title + meta「Ep N · 今天 · M:SS」+ trailing lock。 */
function EpisodeRow({ ep, onOpen }: { ep: EpisodeFixture; onOpen?: () => void }) {
  // shell 路徑：可點 push player。parity 路徑（無 onOpen）維持非互動 div（DOM 不變）。
  const navProps = onOpen
    ? {
        role: 'button' as const,
        tabIndex: 0,
        onClick: onOpen,
        onKeyDown: (e: ReactKeyboardEvent) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onOpen()
          }
        },
      }
    : {}
  return (
    <div className="pel-row" {...navProps}>
      <div className="pel-row-main">
        <div className="pel-row-title">{ep.title}</div>
        <div className="pel-row-meta">
          <span className="pel-row-ep">Ep {ep.episodeNumber}</span>
          <span className="pel-row-sep">·</span>
          <span className="pel-row-date">{ep.date}</span>
          <span className="pel-row-sep">·</span>
          <span className="pel-row-duration">{ep.duration}</span>
        </div>
      </div>
      <span className="pel-row-accessory">
        <LockFillIcon size={12} />
      </span>
    </div>
  )
}

function EmptyBody({ fixture }: { fixture: PodcastEpisodeListFixture }) {
  const empty = fixture.empty
  if (!empty) return null
  return (
    <div className="pel-empty">
      {/* VocabEmptyStateCard：白卡置中（AppSectionCard .vocab） */}
      <div className="pel-empty-card">
        <WaveformSlashIcon className="pel-empty-icon" size={30} strokeWidth={1.4} />
        <div className="pel-empty-title">{empty.title}</div>
        <div className="pel-empty-desc">{empty.description}</div>
      </div>
    </div>
  )
}

/**
 * waves pattern overlay — 對齊 NotebookCoverPattern.waves Canvas：
 * amplitude 8、wavelength 30、row spacing 20、white opacity 0.12、lineWidth 1.2。
 * cover 136×136，rows from y=10 stepping 20。（沿用 podcast-hero CoverWaves。）
 */
function CoverWaves() {
  const size = 136
  const amplitude = 8
  const wavelength = 30
  const spacing = 20
  const rows: string[] = []
  for (let yOffset = spacing / 2; yOffset < size + amplitude; yOffset += spacing) {
    let d = `M 0 ${yOffset}`
    for (let x = 0; x <= size; x += 2) {
      const y = yOffset + amplitude * Math.sin((x / wavelength) * Math.PI * 2)
      d += ` L ${x} ${y.toFixed(2)}`
    }
    rows.push(d)
  }
  return (
    <svg
      className="pel-hero-cover-waves"
      viewBox={`0 0 ${size} ${size}`}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      {rows.map((d, i) => (
        <path key={i} d={d} fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth={1.2} />
      ))}
    </svg>
  )
}

function formatDuration(sec: number): string {
  const total = Math.trunc(sec)
  return `${Math.trunc(total / 60)}:${String(total % 60).padStart(2, '0')}`
}
