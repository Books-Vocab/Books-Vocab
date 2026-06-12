import type { ScenarioId } from '../../harness/scenarios'

/**
 * PodcastShelf fixtures — iOS `PodcastShelfScenarios.swift` 的鏡像。shelf =
 * section 標題 + 橫向 rail（`PodcastContinueRailCard` × N）。每態餵
 * `PodcastFixtures.renderModel(for:)` 攤平後的 (series × episodes × progress)。
 *
 * 資料 SoT = `PodcastFixtures.swift`：
 *   continueSeries：title "Atomic Habits Unpacked"，color = NotebookPalette.defaultHex
 *     = "#AFC2D3"（waves pattern）。defaultHex 即海洋資料色，無需 legacy migration。
 *   episode.displayTitle = "Ep \(n) · \(title)"。
 *   fraction = lastPlayedTime==nil ? 0 : clamp(played/duration)（fraction>0 才畫膠囊）。
 *   remaining = lastPlayedTime==nil ? null : "還剩 " + PodcastClock.format(duration-played)
 *     （PodcastClock：h>0 → "%d:%02d:%02d"，否則 "%d:%02d"；zh-Hant catalog 語系）。
 *   default durationSec = 1832。
 *
 * shelfContinue（4 卡）：
 *   1) Ep2 "On Deep Work"     dur 1832 played 612  → frac 612/1832,  rem 1220s = 20:20
 *   2) Ep5 "A Very Long…"     dur 5432 played 1700 → frac 1700/5432, rem 3732s = 1:02:12
 *   3) Ep8 "Marathon Session" dur 12345 played 321 → frac 321/12345, rem 12024s = 3:20:24
 *   4) Ep1 "The Comfort Crisis" dur 1832 played nil → frac 0,         rem null
 * shelfSingle = 僅卡 1。
 *
 * Long shelf title 場景：同 shelfContinue items，僅 shelf 標題替換為長字串（驗
 * sectionTitle lineLimit(1) tail 截斷）。A11y3 = shelfContinue + .accessibility3，但
 * AppFonts 固定字級不隨 dynamicType 縮放 → catalog PNG 與 Full 逐字節相同（已驗
 * md5 一致），web 無需特殊處理。
 */

const COVER_OCEAN = '#AFC2D3' // token-allow: notebook palette default data color (NotebookPalette.defaultHex)

export interface ShelfCard {
  coverColor: string
  coverName: string
  title: string
  episodeDisplay: string
  fraction: number
  remaining: string | null
}

export interface ShelfFixture {
  shelfTitle: string
  cards: ShelfCard[]
}

const card = (
  coverName: string,
  episodeDisplay: string,
  fraction: number,
  remaining: string | null,
): ShelfCard => ({
  coverColor: COVER_OCEAN,
  coverName,
  title: coverName,
  episodeDisplay,
  fraction,
  remaining,
})

const CONTINUE_CARDS: ShelfCard[] = [
  card('Atomic Habits Unpacked', 'Ep 2 · On Deep Work', 612 / 1832, '還剩 20:20'),
  card(
    'Atomic Habits Unpacked',
    'Ep 5 · A Very Long Episode Title That Should Truncate Cleanly',
    1700 / 5432,
    '還剩 1:02:12',
  ),
  card('Atomic Habits Unpacked', 'Ep 8 · Marathon Session', 321 / 12345, '還剩 3:20:24'),
  card('Atomic Habits Unpacked', 'Ep 1 · The Comfort Crisis', 0, null),
]

export const PODCAST_SHELF_FIXTURES: Record<ScenarioId<'podcast-shelf'>, ShelfFixture> = {
  'continue-full': {
    shelfTitle: '繼續收聽',
    cards: CONTINUE_CARDS,
  },
  'single-card': {
    shelfTitle: '繼續收聽',
    cards: [CONTINUE_CARDS[0]],
  },
  'long-shelf-title': {
    shelfTitle: '繼續收聽：你最近開始但還沒聽完的所有單集都在這裡',
    cards: CONTINUE_CARDS,
  },
  a11y3: {
    shelfTitle: '繼續收聽',
    cards: CONTINUE_CARDS,
  },
}
