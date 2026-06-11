import type { ScenarioId } from '../../harness/scenarios'

export type BookFormat = 'epub' | 'pdf' | 'txt' | 'md'

export interface BookFixture {
  title: string
  author: string
  format: BookFormat
  /** 預先固化的相對日期字串 — Catalog 快照當下 LocaleAwareFormatter 的輸出。
   *  web fixture 不做活日期運算，capture 才能 deterministic。 */
  dateLabel: string
  /** 0..1；scenario seed 未設定 progression（nil → 0，progress bar 只剩 track）。 */
  progression: number
  needsICloudDownload: boolean
}

function book(title: string, author: string, format: BookFormat, dateLabel: string): BookFixture {
  return { title, author, format, dateLabel, progression: 0, needsICloudDownload: true }
}

// 與 BookshelfViewScenarios.seed 同序（dateLastRead 新→舊）。
const POPULATED: BookFixture[] = [
  book('Atomic Habits', 'James Clear', 'epub', '0秒後'),
  book('Deep Work', 'Cal Newport', 'pdf', '2天前'),
  book('Flow', 'Mihaly Csikszentmihalyi', 'epub', '5天前'),
  book('Meditations', 'Marcus Aurelius', 'txt', '1週前'),
  book('On Writing Well', 'William Zinsser', 'md', '2週前'),
]

export function bookshelfFixture(scenario: ScenarioId): BookFixture[] {
  switch (scenario) {
    case 'empty':
      return []
    case 'single':
      return POPULATED.slice(0, 1)
    case 'populated':
      return POPULATED
  }
}
