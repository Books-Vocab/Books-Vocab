import type { CSSProperties } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import {
  metaLine,
  PODCAST_HOME_FIXTURES,
  type ContinueItem,
  type SeriesCard,
} from './fixtures'
import { PatternOverlay, PlayFillIcon, StarFillIcon, WaveformBadgeIcon } from './icons'
import './podcast-home.css'

/**
 * PodcastHomeView surface — iOS `PodcastHomeView.swift` 的 web 鏡像（播客頂層 section
 * full-screen，.fill 不透明 scene）。
 *
 * view tree（PodcastHomeView.body → ZStack(pageBackground) + content/empty）：
 *   .navigationTitle("播客") large title（serif 34 bold）
 *   content = ScrollView { VStack(.leading, spacing s5=20) [
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
  const f = PODCAST_HOME_FIXTURES[scenario]

  return (
    <div className="podcast-home">
      <header className="ph-nav">
        <h1 className="ph-nav-title">播客</h1>
      </header>

      {f.empty ? (
        <EmptyState />
      ) : (
        <main className="ph-scroll">
          <div className="ph-content">
            {f.continueItems.length > 0 && (
              <ContinueShelf items={f.continueItems} />
            )}
            <SeriesGridSection
              series={f.series}
              hasContinueShelf={f.continueItems.length > 0}
            />
          </div>
        </main>
      )}
    </div>
  )
}

/** 繼續收聽 shelf — PodcastShelf：serif 標題 + 橫向 rail 卡列。 */
function ContinueShelf({ items }: { items: ContinueItem[] }) {
  return (
    <section className="ph-shelf">
      <h2 className="ph-section-title">繼續收聽</h2>
      <div className="ph-shelf-scroll">
        <div className="ph-shelf-row">
          {items.map((item, i) => (
            <ContinueRailCard key={`${item.title}-${i}`} item={item} />
          ))}
        </div>
      </div>
    </section>
  )
}

/** PodcastContinueRailCard（cardWidth 150）。 */
function ContinueRailCard({ item }: { item: ContinueItem }) {
  return (
    <div className="ph-rail-card" style={{ '--ph-cover': item.coverColor } as CSSProperties}>
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
}: {
  series: SeriesCard[]
  hasContinueShelf: boolean
}) {
  return (
    <>
      {hasContinueShelf && <h2 className="ph-section-title">所有節目</h2>}
      <div className={`ph-grid${hasContinueShelf ? '' : ' ph-grid-top'}`}>
        {series.map((s, i) => (
          <SeriesCardView key={`${s.title}-${i}`} series={s} />
        ))}
      </div>
    </>
  )
}

/** PodcastSeriesCard（poster tile，cover 210）。 */
function SeriesCardView({ series }: { series: SeriesCard }) {
  return (
    <div className="ph-series-card" style={{ '--ph-cover': series.coverColor } as CSSProperties}>
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
