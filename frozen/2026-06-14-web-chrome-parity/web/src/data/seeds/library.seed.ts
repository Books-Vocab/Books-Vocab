// Library domain seed — the demo bookshelf + reading positions. Lifted verbatim
// from the legacy api/mock/data.ts (MOCK_LIBRARY_BOOKS).

export interface BookSeed {
  id: string
  clientBookId: string
  title: string
  author: string | null
  language: string | null
  format: string | null // epub | pdf | txt | md
  notebookId: string | null
  /** Reading progress 0..1 (BookMetadataResponse.progression). */
  progression: number | null
  /** Opaque reader locator, or null. */
  locator: string | null
  /** ISO8601 position update timestamp, or null. */
  positionUpdatedAt: string | null
}

export const BOOK_SEEDS: BookSeed[] = [
  { id: 'book-1', clientBookId: 'atomic-habits-epub', title: 'Atomic Habits', author: 'James Clear', language: 'en', format: 'epub', notebookId: null, progression: 0.15, locator: null, positionUpdatedAt: null },
  { id: 'book-2', clientBookId: 'deep-work-pdf', title: 'Deep Work', author: 'Cal Newport', language: 'en', format: 'pdf', notebookId: null, progression: 0.0, locator: null, positionUpdatedAt: null },
  { id: 'book-3', clientBookId: 'flow-epub', title: 'Flow', author: 'Mihaly Csikszentmihalyi', language: 'en', format: 'epub', notebookId: null, progression: 0.0, locator: null, positionUpdatedAt: null },
  { id: 'book-4', clientBookId: 'meditations-txt', title: 'Meditations', author: 'Marcus Aurelius', language: 'en', format: 'txt', notebookId: null, progression: 0.0, locator: null, positionUpdatedAt: null },
  { id: 'book-5', clientBookId: 'on-writing-well-md', title: 'On Writing Well', author: 'William Zinsser', language: 'en', format: 'md', notebookId: null, progression: 0.0, locator: null, positionUpdatedAt: null },
]
