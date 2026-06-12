import type { ScenarioId } from '../../harness/scenarios'

/**
 * BookCard fixtures — 鏡像 ios/BooksAndVocab/Debug/Scenarios/BookCardScenarios.swift
 * 的 6 個 spec。relative-date 字串以 catalog 渲染（fixtureReferenceDate
 * = 2024-06-04 11:00 UTC，LocaleAwareFormatter .short）實測值固化。
 */
export type BookFormat = 'epub' | 'pdf' | 'txt'

export interface BookCardFixture {
  title: string
  author: string
  format: BookFormat
  /** 0..1；null → 0% 占位（track only，% 隱形）。 */
  progression: number
  /** 相對日期短字串；空 → 單空格占位（等高契約）。 */
  dateLabel: string
  /** iCloud 待下載徽章（fixture book 無本地檔 → 全 scenario 皆顯示）。 */
  needsICloudDownload: boolean
}

export const BOOK_CARD_FIXTURES: Record<ScenarioId<'book-card'>, BookCardFixture> = {
  'placeholder-epub': {
    title: '原子習慣',
    author: 'James Clear',
    format: 'epub',
    progression: 0,
    dateLabel: '',
    needsICloudDownload: true,
  },
  'pdf-badge': {
    title: '深度工作論文集',
    author: 'Cal Newport',
    format: 'pdf',
    progression: 0,
    dateLabel: '',
    needsICloudDownload: true,
  },
  'progress-mid': {
    title: '刻意練習',
    author: 'Anders Ericsson',
    format: 'epub',
    progression: 0.42,
    dateLabel: '5天前',
    needsICloudDownload: true,
  },
  'progress-complete': {
    title: '心流',
    author: 'Mihaly Csikszentmihalyi',
    format: 'epub',
    progression: 1.0,
    dateLabel: '1天前',
    needsICloudDownload: true,
  },
  'long-title': {
    title: '尋找心流：最優體驗的科學與日常生活中的應用實踐指南',
    author: 'Mihaly Csikszentmihalyi & Co-Author With A Rather Long Name',
    format: 'txt',
    progression: 0.08,
    dateLabel: '2週前',
    needsICloudDownload: true,
  },
  // A11y3 = midProgress spec + dynamicTypeSize .accessibility3。catalog 實際
  // 渲染與 Mid 視覺一致（component scene 內字級未顯著放大），故沿用相同內容。
  a11y3: {
    title: '刻意練習',
    author: 'Anders Ericsson',
    format: 'epub',
    progression: 0.42,
    dateLabel: '5天前',
    needsICloudDownload: true,
  },
}
