import type { ScenarioId } from '../../harness/scenarios'

/**
 * Podcast Episode List fixtures — 逐字鏡像
 * `PodcastEpisodeListViewScenarios.swift` 的 seed。
 *
 * Scene 注入 `CatalogPreviewAuth(isLoggedIn: true)` 但**無 Pro** →
 * `PodcastAccess.tier(hasProAccess:false, hasToken:true) = .free`。
 * episode `previewAvailable` default=false（seed 不設）→ 每集 `showsProLock`=true
 * （free 在 ep1 也需 previewAvailable 才能預覽）→
 *   · 全部 4 row 顯示 lock.fill / tertiaryText（trailingAccessory locked 分支）
 *   · heroContinue 的 continueEpisode = ep1（無 progress）→ heroAction = .upgrade
 *     （free + showsProLock → .upgrade）→ disc=lock.fill on brandHero、
 *      eyebrow=「升級 Pro」、title=displayTitle「Ep 1 · The Comfort Crisis」、
 *      trailing=lock.fill、navigatesToPlayer=false（actionable=true，brandHero disc）。
 *
 * series：title「Atomic Habits Unpacked」、hostNames ["Ava Chen","Leo Park"]、
 *   color #4A90D9（→ legacyMigration #AFC2D3 cover data 色）、coverPattern .waves。
 *   episodeCount / totalDurationSec **未設** → metaText = hosts only =
 *   「Ava Chen, Leo Park」（episodeCount>0 / totalDuration>0 兩段皆跳過）。
 *
 * episodes（seed 序，episodeNumber 升冪；default sort .ascending）：
 *   (1,"The Comfort Crisis",1832) → 30:32
 *   (2,"On Deep Work",2014)       → 33:34
 *   (3,"Habit Stacking in Practice",1567) → 26:07
 *   (4,"Members-only Deep Dive",2456)     → 40:56
 * createdAt = PodcastEpisode init default（now）→ formatDate = 「今天」。
 * audioAvailable / subtitleAvailable / previewAvailable 皆 model default
 *   （audioAvailable=true、subtitleAvailable=false、previewAvailable=false）。
 *   → row 無 captions.bubble；trailing 全 lock（locked 早於 audio/completed 分支）。
 */

export interface EpisodeFixture {
  episodeNumber: number
  title: string
  /** formatDuration(durationSec) = "M:SS"（M 不補零、S 補零）。 */
  duration: string
  /** createdAt today → formatDate「今天」。 */
  date: string
}

function formatDuration(sec: number): string {
  const total = Math.trunc(sec)
  return `${Math.trunc(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

export interface PodcastEpisodeListFixture {
  /** nav title = series.title（inline，極淡 chrome）。 */
  navTitle: string
  /** hero cover/title。 */
  seriesTitle: string
  /** metaText（hosts only）；null = 無 meta。 */
  meta: string | null
  /** continue card（heroAction=.upgrade）。 */
  continueCard: {
    eyebrow: string
    /** episode.displayTitle = "Ep N · title"。 */
    title: string
  } | null
  /** 集數 section 標題。 */
  sectionTitle: string
  /** sort menu 當前選項 label。 */
  sortLabel: string
  episodes: EpisodeFixture[]
  /** empty 態（VocabSceneShell .empty）。 */
  empty: {
    title: string
    description: string
  } | null
}

const SERIES_TITLE = 'Atomic Habits Unpacked'
const META = 'Ava Chen, Leo Park'

const EPISODES: EpisodeFixture[] = [
  { episodeNumber: 1, title: 'The Comfort Crisis', duration: formatDuration(1832), date: '今天' },
  { episodeNumber: 2, title: 'On Deep Work', duration: formatDuration(2014), date: '今天' },
  { episodeNumber: 3, title: 'Habit Stacking in Practice', duration: formatDuration(1567), date: '今天' },
  { episodeNumber: 4, title: 'Members-only Deep Dive', duration: formatDuration(2456), date: '今天' },
]

export const PODCAST_EPISODE_LIST_FIXTURES: Record<
  ScenarioId<'podcast-episode-list'>,
  PodcastEpisodeListFixture
> = {
  populated: {
    navTitle: SERIES_TITLE,
    seriesTitle: SERIES_TITLE,
    meta: META,
    continueCard: {
      eyebrow: '升級 Pro',
      title: 'Ep 1 · The Comfort Crisis',
    },
    sectionTitle: '集數',
    sortLabel: '集數由小到大',
    episodes: EPISODES,
    empty: null,
  },
  empty: {
    navTitle: SERIES_TITLE,
    seriesTitle: SERIES_TITLE,
    meta: META,
    continueCard: null,
    sectionTitle: '集數',
    sortLabel: '集數由小到大',
    episodes: [],
    empty: {
      title: '尚無集數',
      description: '此系列目前沒有可播放的集數',
    },
  },
}

/** cover data 色：series.color #4A90D9 → legacyMigration → #AFC2D3（海洋）。 */
export const COVER_COLOR = '#AFC2D3'
