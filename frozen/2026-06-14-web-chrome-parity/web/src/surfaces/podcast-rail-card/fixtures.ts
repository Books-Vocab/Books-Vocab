import type { ScenarioId } from '../../harness/scenarios'

/**
 * PodcastContinueRailCard scenario fixtures — 對齊 PodcastShelfCardsScenarios.swift
 * 「Podcast Continue Rail Card」5 態。
 *
 * 每態以 PodcastContinueRailCardScene(seriesTitle, epTitle, epNumber, duration, played)
 * 構造。web fixture 直接把 iOS 邏輯（fraction / remaining clock）攤平成預算值，
 * 不在 web 重算（與 SoT 對齊）：
 *   - coverColor：series.color="#4A90D9" 經 NotebookPalette.legacyMigration →
 *     "#AFC2D3"（"海洋" Morandi）。此為 notebook palette 資料色（token-allow
 *     豁免，非視覺 token），故以資料字面承載於 fixture，不進 design token。
 *   - coverName = series.title（cover 中央白字，body 17 semibold，lineLimit 2 居中）。
 *   - title = series.title（卡下第一行，caption=sans 12 bold）。
 *   - episodeDisplay = "Ep \(epNumber) · \(epTitle)"（PodcastEpisode.displayTitle，
 *     caption2=sans 11 regular）。
 *   - fraction = played==nil ? 0 : clamp(played/duration)；fraction>0 才畫 ProgressCapsule。
 *   - remaining = played==nil ? null : PodcastClock.format(duration-played)；
 *     文案 "還剩 %@"（zh-Hant，catalog 渲染語系），mono 10 bold。
 *
 * PodcastClock.format：h>0 → "%d:%02d:%02d"，否則 "%d:%02d"。
 * a11y3 場景 iOS 套 .accessibility3，但 AppFonts 為固定字級（非 system text style），
 * 不隨 dynamicType 縮放 → catalog PNG 與其餘態同尺寸，web 無需特殊處理。
 */
const COVER_OCEAN = '#AFC2D3' // token-allow: notebook palette data color (legacy #4A90D9 → 海洋)

export interface RailCardFixture {
  coverColor: string
  coverName: string
  title: string
  episodeDisplay: string
  fraction: number
  remaining: string | null
}

export const PODCAST_RAIL_CARD_FIXTURES: Record<ScenarioId<'podcast-rail-card'>, RailCardFixture> = {
  // Resume: duration 1832, played 612 → fraction 0.334；remaining 1220s = 20:20
  resume: {
    coverColor: COVER_OCEAN,
    coverName: 'Atomic Habits Unpacked',
    title: 'Atomic Habits Unpacked',
    episodeDisplay: 'Ep 2 · On Deep Work',
    fraction: 612 / 1832,
    remaining: '還剩 20:20',
  },
  // No progress: played nil → fraction 0（無 bar）、remaining null（無文字）
  'no-progress': {
    coverColor: COVER_OCEAN,
    coverName: 'Atomic Habits Unpacked',
    title: 'Atomic Habits Unpacked',
    episodeDisplay: 'Ep 1 · The Comfort Crisis',
    fraction: 0,
    remaining: null,
  },
  // Long title: series + episode 皆長 → 單行 tail 截斷；duration 5432, played 1700 → 3732s = 1:02:12
  'long-title': {
    coverColor: COVER_OCEAN,
    coverName: 'Finding Flow: The Science of Optimal Experience',
    title: 'Finding Flow: The Science of Optimal Experience',
    episodeDisplay: 'Ep 12 · A Very Long Episode Title That Must Truncate Cleanly On One Line',
    fraction: 1700 / 5432,
    remaining: '還剩 1:02:12',
  },
  // Large numbers: duration 12345, played 321 → fraction 0.026；12024s = 3:20:24
  'large-numbers': {
    coverColor: COVER_OCEAN,
    coverName: 'The Long Haul',
    title: 'The Long Haul',
    episodeDisplay: 'Ep 8 · Marathon Session',
    fraction: 321 / 12345,
    remaining: '還剩 3:20:24',
  },
  // A11y3: duration 1832, played 900 → fraction 0.491；932s = 15:32
  a11y3: {
    coverColor: COVER_OCEAN,
    coverName: 'Hidden Hand',
    title: 'Hidden Hand',
    episodeDisplay: 'Ep 3 · Origins',
    fraction: 900 / 1832,
    remaining: '還剩 15:32',
  },
}
