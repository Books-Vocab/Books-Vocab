import { useCallback, useEffect, useMemo, useState } from 'react'
import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent } from 'react'
import { useApi } from '../../api/ApiContext'
import type { PodcastProgressResponse, PodcastSeriesSummary } from '../../api/types'
import type { ScenarioId } from '../../harness/scenarios'
import {
  metaLine,
  PODCAST_HOME_FIXTURES,
  type ContinueItem,
  type SeriesCard,
} from './fixtures'
import { PatternOverlay, PlayFillIcon, StarFillIcon, WaveformBadgeIcon } from './icons'
import { useShellNav } from '../../shell/ShellNavContext'
import { pushTargetFor, screenFor } from '../../shell/nav'
import { PodcastNowPlaying } from '../podcast/PodcastNowPlaying'
import './podcast-home.css'

/**
 * PodcastHomeView surface — iOS `PodcastHomeView.swift` 的 web 鏡像（播客頂層 section
 * full-screen，.fill 不透明 scene）。
 *
 * view tree（PodcastHomeView.body → ZStack(pageBackground) + content/empty）：
 *   .navigationTitle("播客") large title（serif 34 bold）
 *   content = ScrollView { VStack(.leading, spacing s5=20)[
 *     if !continueItems.isEmpty: continueShelf.padding(.top, s2=8)
 *     seriesGridSection
 *   ] }
 *   continueShelf = PodcastShelf(title:"繼續收聽") { LazyHStack(spacing s3=12) rail cards }
 *     · shelf title = serif sectionTitle(18 bold) primaryText, h-pad pageHorizontalPadding(20)
 *     · LazyHStack h-pad 20；卡間 s3=12；卡 = PodcastContinueRailCard(width 150)
 *   seriesGridSection：
 *     · 有 continue shelf 時冠 Text("所有節目") serif 18 bold primaryText, h-pad 20
 *     · LazyVGrid(adaptive min150, spacing sectionSpacing=24) PodcastSeriesCard(cover 210)
 *       h-pad 20；.padding(.top, continueItems.isEmpty ? s2=8 : 0)
 *   empty = AppEmptyStateContent(.bookshelf)：waveform 48 ultraLight quaternary +
 *     「尚無播客」subhead15 bold secondary +「追蹤喜歡的節目，從這裡開始收聽」caption12
 *     tertiary +「下拉重新整理以同步節目」caption12 tertiary×0.7，spacing 6。
 *
 * full-screen scene → 不透明（catalog alpha-mean=1），無 crop/transparent。
 */

export function PodcastHomeScreen({ scenario }: { scenario: ScenarioId<'podcast-home'> }) {
  const shell = new URLSearchParams(window.location.search).get('shell') === '1'
  if (shell) {
    return <PodcastHomeScreenApi />
  }
  return <PodcastHomeScreenFixture scenario={scenario} />
}

function PodcastHomeScreenFixture({ scenario }: { scenario: ScenarioId<'podcast-home'> }) {
  const f = PODCAST_HOME_FIXTURES[scenario]
  return <PodcastHomeBody fixture={f} />
}

function PodcastHomeScreenApi() {
  const api = useApi()
  const [series, setSeries] = useState<PodcastSeriesSummary[]>([])
  const [progress, setProgress] = useState<PodcastProgressResponse[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [s, p] = await Promise.all([api.podcast.series(), api.podcast.progress().catch(() => ({ items: [] }))])
      setSeries(s)
      setProgress(p.items)
    } catch {
      // ignore: series() is anonymous and should not fail; progress may 401 for guests
    } finally {
      setLoading(false)
    }
  }, [api])

  useEffect(() => {
    load()
  }, [load])

  const fixture = useMemo((): PodcastHomeFixture => {
    if (loading) {
      return { empty: false, continueItems: [], series: [] }
    }
    if (series.length === 0) {
      return { empty: true, continueItems: [], series: [] }
    }
    const mappedSeries: SeriesCard[] = series.map((s) => ({
      seriesId: s.id != null ? String(s.id) : undefined,
      coverColor: '#AFC2D3',
      coverPattern: 'waves',
      title: String(s.title ?? s.id ?? ''),
      hosts: String(s.author ?? '').split(',').map((h) => h.trim()).filter(Boolean),
      count: Number(s.episode_count ?? 0),
      isFollowed: false,
    }))
    const mappedContinue: ContinueItem[] = progress.map((pr) => {
      const matched = series.find((s) => s.id === pr.series_id)
      return {
        seriesId: pr.series_id != null ? String(pr.series_id) : undefined,
        epNum: Number(pr.ep_num),
        coverColor: '#AFC2D3',
        coverPattern: 'waves',
        coverName: String(matched?.title ?? pr.series_id),
        title: String(matched?.title ?? pr.series_id),
        episodeDisplay: `Ep ${pr.ep_num}`,
        fraction: clamp01(pr.position_sec / Math.max(pr.duration_sec, 1)),
        remaining: formatRemaining(Math.max(0, pr.duration_sec - pr.position_sec)),
      }
    })
    return {
      empty: false,
      continueItems: mappedContinue,
      series: mappedSeries,
    }
  }, [loading, series, progress])

  // shell 路徑：點系列卡 → push podcast-episode-list（攜真實 seriesId）；
  // 點繼續收聽 rail → 直開 player（攜 seriesId + epNum）。parity 路徑不傳此
  // callback，卡片維持非互動 div，故首屏 DOM 與靜態 PNG 逐位元一致。
  const nav = useShellNav()
  const openSeries = (seriesId?: string) => {
    const home = screenFor('podcast-home')
    const target = pushTargetFor(home, 'open-podcast-series', seriesId ? { seriesId } : undefined)
    if (target) nav.navigate(target)
  }
  const openEpisode = (seriesId?: string, epNum?: number) => {
    // 先推系列集數列表，再推 player：保留 master-detail 的深層返回語意。
    const home = screenFor('podcast-home')
    const list = pushTargetFor(home, 'open-podcast-series', seriesId ? { seriesId } : undefined)
    if (!list) return
    nav.navigate(list)
    const player = pushTargetFor(
      list,
      'open-podcast-episode',
      seriesId ? { seriesId, epNum } : undefined,
    )
    if (player) nav.navigate(player)
  }
  return (
    <>
      <PodcastHomeBody fixture={fixture} onOpenSeries={openSeries} onOpenEpisode={openEpisode} />
      {/* Persistent now-playing layer: the mini-player floats above this tab root
          once an episode is engaged, surviving the push into series/episode/player. */}
      <PodcastNowPlaying />
    </>
  )
}

function PodcastHomeBody({
  fixture,
  onOpenSeries,
  onOpenEpisode,
}: {
  fixture: PodcastHomeFixture
  /** shell 路徑：點系列卡 → episode-list。parity 路徑省略 → 卡片非互動。 */
  onOpenSeries?: (seriesId?: string) => void
  /** shell 路徑：點繼續收聽 → 直開 player。parity 路徑省略 → 卡片非互動。 */
  onOpenEpisode?: (seriesId?: string, epNum?: number) => void
}) {
  return (
    <div className="podcast-home">
      <header className="ph-nav">
        <h1 className="ph-nav-title">播客</h1>
      </header>

      {fixture.empty ? (
        <EmptyState />
      ) : (
        <main className="ph-scroll">
          <div className="ph-content">
            {fixture.continueItems.length > 0 && (
              <ContinueShelf items={fixture.continueItems} onOpenEpisode={onOpenEpisode} />
            )}
            <SeriesGridSection
              series={fixture.series}
              hasContinueShelf={fixture.continueItems.length > 0}
              onOpenSeries={onOpenSeries}
            />
          </div>
        </main>
      )}
    </div>
  )
}

/** 繼續收聽 shelf — PodcastShelf：serif 標題 + 橫向 rail 卡列。 */
function ContinueShelf({
  items,
  onOpenEpisode,
}: {
  items: ContinueItem[]
  onOpenEpisode?: (seriesId?: string, epNum?: number) => void
}) {
  return (
    <section className="ph-shelf">
      <h2 className="ph-section-title">繼續收聽</h2>
      <div className="ph-shelf-scroll">
        <div className="ph-shelf-row">
          {items.map((item, i) => (
            <ContinueRailCard key={`${item.title}-${i}`} item={item} onOpenEpisode={onOpenEpisode} />
          ))}
        </div>
      </div>
    </section>
  )
}

/** PodcastContinueRailCard（cardWidth 150）。 */
function ContinueRailCard({
  item,
  onOpenEpisode,
}: {
  item: ContinueItem
  onOpenEpisode?: (seriesId?: string, epNum?: number) => void
}) {
  // shell 路徑：可點直開 player。parity 路徑（無 callback）維持非互動 div（DOM 不變）。
  const interactive = onOpenEpisode != null
  const navProps = interactive
    ? {
        role: 'button' as const,
        tabIndex: 0,
        onClick: () => onOpenEpisode(item.seriesId, item.epNum),
        onKeyDown: (e: ReactKeyboardEvent) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onOpenEpisode(item.seriesId, item.epNum)
          }
        },
      }
    : {}
  return (
    <div
      className="ph-rail-card"
      style={{ '--ph-cover': item.coverColor } as CSSProperties}
      {...navProps}
    >
      <div className="ph-rail-cover">
        <PatternOverlay pattern={item.coverPattern} />
        <span className="ph-rail-cover-name">{item.coverName}</span>
        <span className="ph-rail-play" aria-hidden="true">
          <PlayFillIcon className="ph-rail-play-glyph" />
        </span>
      </div>
      <div className="ph-rail-meta">
        <span className="ph-rail-title">{item.title}</span>
        <span className="ph-rail-episode">{item.episodeDisplay}</span>
        {item.fraction > 0 && (
          <div className="ph-rail-progress">
            <span
              className="ph-rail-progress-fill"
              style={{ width: `${item.fraction * 100}%` }}
            />
          </div>
        )}
        {item.remaining != null && <span className="ph-rail-remaining">{item.remaining}</span>}
      </div>
    </div>
  )
}

/** 所有節目 grid — 有 continue shelf 時冠標題。 */
function SeriesGridSection({
  series,
  hasContinueShelf,
  onOpenSeries,
}: {
  series: SeriesCard[]
  hasContinueShelf: boolean
  onOpenSeries?: (seriesId?: string) => void
}) {
  return (
    <>
      {hasContinueShelf && <h2 className="ph-section-title">所有節目</h2>}
      <div className={`ph-grid${hasContinueShelf ? '' : ' ph-grid-top'}`}>
        {series.map((s, i) => (
          <SeriesCardView key={`${s.title}-${i}`} series={s} onOpenSeries={onOpenSeries} />
        ))}
      </div>
    </>
  )
}

/** PodcastSeriesCard（poster tile，cover 210）。 */
function SeriesCardView({
  series,
  onOpenSeries,
}: {
  series: SeriesCard
  onOpenSeries?: (seriesId?: string) => void
}) {
  // shell 路徑：可點 push episode-list。parity 路徑（無 callback）維持非互動 div。
  const interactive = onOpenSeries != null
  const navProps = interactive
    ? {
        role: 'button' as const,
        tabIndex: 0,
        onClick: () => onOpenSeries(series.seriesId),
        onKeyDown: (e: ReactKeyboardEvent) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onOpenSeries(series.seriesId)
          }
        },
      }
    : {}
  return (
    <div
      className="ph-series-card"
      style={{ '--ph-cover': series.coverColor } as CSSProperties}
      {...navProps}
    >
      <div className="ph-series-cover">
        <PatternOverlay pattern={series.coverPattern} />
        <span className="ph-series-cover-name">{series.title}</span>
        {series.isFollowed && (
          <div className="ph-series-star" aria-hidden="true">
            <StarFillIcon className="ph-series-star-icon" />
          </div>
        )}
        <div className="ph-series-badge" aria-hidden="true">
          <WaveformBadgeIcon className="ph-series-badge-icon" />
        </div>
      </div>
      <div className="ph-series-meta">
        <span className="ph-series-title">{series.title}</span>
        <span className="ph-series-subtitle">{metaLine(series)}</span>
      </div>
    </div>
  )
}

/** Empty — AppEmptyStateContent(.bookshelf style)。 */
function EmptyState() {
  return (
    <main className="ph-scroll ph-empty">
      <div className="ph-empty-content">
        {/* waveform symbol(size 48, ultraLight) quaternary；列等高豎條波形 */}
        <WaveformGlyph />
        <p className="ph-empty-title">尚無播客</p>
        <p className="ph-empty-description">追蹤喜歡的節目，從這裡開始收聽</p>
        <p className="ph-empty-guidance">下拉重新整理以同步節目</p>
      </div>
    </main>
  )
}

/** 空狀態大型 waveform（SF `waveform`, size 48 ultraLight）。豎條起伏，細描邊。 */
function WaveformGlyph() {
  return (
    <svg
      className="ph-empty-icon"
      width="48"
      height="48"
      viewBox="0 0 48 48"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      aria-hidden="true"
      focusable="false"
    >
      <line x1="9" y1="22" x2="9" y2="26" />
      <line x1="15" y1="16" x2="15" y2="32" />
      <line x1="21" y1="11" x2="21" y2="37" />
      <line x1="27" y1="19" x2="27" y2="29" />
      <line x1="33" y1="14" x2="33" y2="34" />
      <line x1="39" y1="20" x2="39" y2="28" />
    </svg>
  )
}

function clamp01(v: number): number {
  return v < 0 ? 0 : v > 1 ? 1 : v
}

function formatRemaining(sec: number): string | null {
  if (sec <= 0) return '還剩 0:00'
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `還剩 ${m}:${String(s).padStart(2, '0')}`
}

export interface PodcastHomeFixture {
  empty: boolean
  continueItems: ContinueItem[]
  series: SeriesCard[]
}
