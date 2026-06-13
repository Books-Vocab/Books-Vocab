import { useMemo, useState } from 'react'
import type { PodcastSeriesSummary } from '../../api/types'
import { RouteTransition, useNavDirection } from '../../motion'
import {
  buildContinueShelf,
  indexCatalog,
  type ContinueShelfItem,
} from '../podcast/continueShelf'
import {
  currentFlowScreen,
  flowDepth,
  initialFlow,
  openEpisode,
  openSeries,
  popFlow,
  type PodcastFlowScreen,
  type PodcastFlowStack,
} from '../podcast/flowNav'
import { tierFromEntitlements, type PodcastTier } from '../podcast/tier'
import { ChevronLeftIcon } from '../../shell/icons'
import { PlayFillIcon } from './icons'
import { usePodcastData } from './usePodcastData'
import { PodcastFlowPlayer } from './PodcastFlowPlayer'
import { PodcastMiniPlayer } from './PodcastMiniPlayer'
import { reopenPlayer, shouldShowMiniPlayer } from './miniPlayer'
import { usePodcastPlayback } from './usePodcastPlayback'
import './podcast-home.css'
import './podcast-flow.css'
import './mini-player.css'

/**
 * Shell-gated functional podcast flow — the live-API sibling of PodcastHomeScreen.
 *
 * Mounted ONLY behind ?shell=1 (PodcastScreen routes to it; the fixture branch
 * is byte-identical and untouched). Wires the real data layer:
 *   - createApiClient() (mock-first, offline): series / progress / entitlements
 *   - inter-surface nav home → episode-list(seriesId) → player(seriesId,epNum)
 *     via the podcast flow stack (frozen shell nav has no podcast params)
 *   - tier gating (guest/free/pro) from user.entitlements() + login state
 *   - continue-shelf derived from podcast.progress()
 *   - subtitle SRT parse synced to audio time (PodcastFlowPlayer)
 *
 * Presentation reuses the existing podcast-home CSS classes so the functional
 * home reads like the parity home; the new functional-only chrome (back bar,
 * episode list, player) lives in podcast-flow.css.
 */
export function PodcastHomeApiStore() {
  const data = usePodcastData()
  const [stack, setStack] = useState<PodcastFlowStack>(() => initialFlow())
  // Single persistent playback engine: one <audio> kept alive across the flow so
  // the mini-player continues playing while you navigate home ↔ list ↔ player.
  const playback = usePodcastPlayback(data.api)

  const tier: PodcastTier = tierFromEntitlements(data.entitlements, data.hasToken)
  const catalog = useMemo(() => indexCatalog(data.series), [data.series])
  const continueItems = useMemo(
    () => buildContinueShelf(data.progress, catalog),
    [data.progress, catalog],
  )

  const screen = currentFlowScreen(stack)
  const depth = flowDepth(stack)
  const canGoBack = depth > 1
  // RouteTransition inputs: stable per-screen identity + inferred push/pop. Same
  // foundation the shell uses (mode="stack") — no hand-rolled transition.
  const routeKey = flowRouteKey(screen, depth)
  const direction = useNavDirection(depth)
  const miniVisible = shouldShowMiniPlayer(playback.nowPlaying, playback.engaged, screen)

  return (
    <div className="podcast-home pf-root" data-mini={miniVisible ? 'true' : undefined}>
      {/* The one persistent audio element. Lives at the flow root (NOT inside a
          screen) so popping back never tears down playback. The playback hook
          owns all transport state; screens are thin views over it. */}
      <audio ref={playback.audioRef} {...playback.audioProps} />

      {canGoBack && (
        <button
          type="button"
          className="pf-back"
          aria-label="返回"
          onClick={() => setStack((s) => popFlow(s))}
        >
          <ChevronLeftIcon size={20} />
        </button>
      )}

      {/* iOS push/pop between home / episode-list / player via the shared
          RouteTransition (incoming slides from the right, outgoing parallax-
          dims; pop reverses; prefers-reduced-motion → instant). */}
      <RouteTransition routeKey={routeKey} direction={direction} mode="stack">
        {screen.route === 'home' && (
          <HomeView
            loading={data.loading}
            series={data.series}
            continueItems={continueItems}
            onOpenSeries={(id) => setStack((s) => openSeries(s, id))}
            onOpenEpisode={(id, ep) => setStack((s) => openEpisode(s, id, ep))}
          />
        )}

        {screen.route === 'episode-list' && (
          <EpisodeListView
            seriesId={screen.seriesId}
            series={catalog.get(screen.seriesId)}
            tier={tier}
            onOpenEpisode={(ep) => setStack((s) => openEpisode(s, screen.seriesId, ep))}
          />
        )}

        {screen.route === 'player' && (
          <PodcastFlowPlayer
            seriesId={screen.seriesId}
            epNum={screen.epNum}
            series={catalog.get(screen.seriesId)}
            tier={tier}
            playback={playback}
          />
        )}
      </RouteTransition>

      {/* Persistent mini-player: animates in once an episode is loaded and the
          full player isn't the visible screen; tap re-opens the player. */}
      <PodcastMiniPlayer
        visible={miniVisible}
        playback={playback}
        onOpen={() => setStack((s) => (playback.nowPlaying ? reopenPlayer(s, playback.nowPlaying) : s))}
      />
    </div>
  )
}

/** Stable AnimatePresence key per flow screen (route + depth + entity id). */
function flowRouteKey(screen: PodcastFlowScreen, depth: number): string {
  switch (screen.route) {
    case 'home':
      return `home:${depth}`
    case 'episode-list':
      return `list:${depth}:${screen.seriesId}`
    case 'player':
      return `player:${depth}:${screen.seriesId}:${screen.epNum}`
  }
}

// ── home ─────────────────────────────────────────────────────────────────────

function HomeView({
  loading,
  series,
  continueItems,
  onOpenSeries,
  onOpenEpisode,
}: {
  loading: boolean
  series: PodcastSeriesSummary[]
  continueItems: ContinueShelfItem[]
  onOpenSeries: (seriesId: string) => void
  onOpenEpisode: (seriesId: string, epNum: number) => void
}) {
  return (
    <>
      <header className="ph-nav">
        <h1 className="ph-nav-title">播客</h1>
      </header>
      {loading ? (
        <main className="ph-scroll">
          <p className="pf-status" role="status">
            載入中…
          </p>
        </main>
      ) : series.length === 0 ? (
        <main className="ph-scroll">
          <p className="pf-status" role="status">
            尚無播客
          </p>
        </main>
      ) : (
        <main className="ph-scroll">
          <div className="ph-content">
            {continueItems.length > 0 && (
              <section className="ph-shelf">
                <h2 className="ph-section-title">繼續收聽</h2>
                <div className="ph-shelf-scroll">
                  <div className="ph-shelf-row">
                    {continueItems.map((item) => (
                      <button
                        type="button"
                        key={`${item.seriesId}-${item.epNum}`}
                        className="pf-rail-button"
                        onClick={() => onOpenEpisode(item.seriesId, item.epNum)}
                      >
                        <ContinueRailCard item={item} />
                      </button>
                    ))}
                  </div>
                </div>
              </section>
            )}
            {continueItems.length > 0 && <h2 className="ph-section-title">所有節目</h2>}
            <div className={`ph-grid${continueItems.length > 0 ? '' : ' ph-grid-top'}`}>
              {series.map((s) => (
                <SeriesGridCard
                  key={String(s.id)}
                  series={s}
                  onOpen={() => onOpenSeries(String(s.id))}
                />
              ))}
            </div>
          </div>
        </main>
      )}
    </>
  )
}

function ContinueRailCard({ item }: { item: ContinueShelfItem }) {
  return (
    <div className="ph-rail-card pf-rail-card">
      <div className="ph-rail-cover">
        <span className="ph-rail-cover-name">{item.seriesTitle}</span>
        <span className="ph-rail-play" aria-hidden="true">
          <PlayFillIcon className="ph-rail-play-glyph" />
        </span>
      </div>
      <div className="ph-rail-meta">
        <span className="ph-rail-title">{item.seriesTitle}</span>
        <span className="ph-rail-episode">{item.episodeDisplay}</span>
        {item.fraction > 0 && (
          <div className="ph-rail-progress">
            <span className="ph-rail-progress-fill" style={{ width: `${item.fraction * 100}%` }} />
          </div>
        )}
        {item.remaining != null && <span className="ph-rail-remaining">{item.remaining}</span>}
      </div>
    </div>
  )
}

function SeriesGridCard({
  series,
  onOpen,
}: {
  series: PodcastSeriesSummary
  onOpen: () => void
}) {
  const title = String(series.title ?? series.id ?? '')
  const count = Number(series.episode_count ?? (Array.isArray(series.episodes) ? series.episodes.length : 0))
  const author = typeof series.author === 'string' ? series.author : ''
  const meta = author ? `${author} · ${count} 集` : `${count} 集`
  return (
    <button type="button" className="ph-series-card pf-series-button" onClick={onOpen}>
      <div className="ph-series-cover">
        <span className="ph-series-cover-name">{title}</span>
      </div>
      <div className="ph-series-meta">
        <span className="ph-series-title">{title}</span>
        <span className="ph-series-subtitle">{meta}</span>
      </div>
    </button>
  )
}

// ── episode list ───────────────────────────────────────────────────────────────

interface OpaqueEpisode {
  ep_num: number
  title: string
  duration_sec: number
}

function readEpisodes(series: PodcastSeriesSummary | undefined): OpaqueEpisode[] {
  const eps = series?.episodes
  if (!Array.isArray(eps)) return []
  return eps
    .filter((e): e is Record<string, unknown> => !!e && typeof e === 'object')
    .map((e) => ({
      ep_num: Number(e.ep_num ?? 0),
      title: typeof e.title === 'string' ? e.title : `Ep ${Number(e.ep_num ?? 0)}`,
      duration_sec: Number(e.duration_sec ?? 0),
    }))
    .filter((e) => e.ep_num > 0)
}

function EpisodeListView({
  seriesId,
  series,
  tier,
  onOpenEpisode,
}: {
  seriesId: string
  series: PodcastSeriesSummary | undefined
  tier: PodcastTier
  onOpenEpisode: (epNum: number) => void
}) {
  const title = String(series?.title ?? seriesId)
  const episodes = readEpisodes(series)
  return (
    <main className="ph-scroll pf-episode-list">
      <header className="pf-detail-nav">
        <span className="pf-detail-title">{title}</span>
      </header>
      {episodes.length === 0 ? (
        <p className="pf-status" role="status">
          此系列目前沒有可播放的集數
        </p>
      ) : (
        <ul className="pf-episodes">
          {episodes.map((ep) => {
            // ep 1 free-preview asset assumed present in mock; gating from tier.
            const previewAvailable = ep.ep_num === 1
            const locked = tier !== 'pro' && !(tier === 'free' && previewAvailable)
            return (
              <li key={ep.ep_num}>
                <button
                  type="button"
                  className="pf-episode-row"
                  data-locked={locked || undefined}
                  onClick={() => onOpenEpisode(ep.ep_num)}
                >
                  <span className="pf-episode-main">
                    <span className="pf-episode-title">{ep.title}</span>
                    <span className="pf-episode-meta">
                      Ep {ep.ep_num} · {formatDuration(ep.duration_sec)}
                    </span>
                  </span>
                  <span className="pf-episode-accessory" aria-hidden="true">
                    {locked ? <LockGlyph /> : <PlayFillIcon className="pf-episode-play" />}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </main>
  )
}

function LockGlyph() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M12 2a5 5 0 0 0-5 5v3H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8a2 2 0 0 0-2-2h-1V7a5 5 0 0 0-5-5zm-3 8V7a3 3 0 0 1 6 0v3z" />
    </svg>
  )
}

function formatDuration(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

export type { OpaqueEpisode }
export { readEpisodes }
