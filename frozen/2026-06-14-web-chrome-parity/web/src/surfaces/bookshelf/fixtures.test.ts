import { describe, expect, it } from 'vitest'
import { bookshelfFixture } from './fixtures'

// 鏡像 ios/BooksAndVocab/Debug/Scenarios/BookshelfViewScenarios.swift 的 seed：
// 書目、格式、排序（dateLastRead 新→舊）與 Catalog 快照渲染出的相對日期字串
// 必須逐字一致，否則 parity diff 會在文字層失真。
describe('bookshelfFixture', () => {
  it('empty scenario has no books', () => {
    expect(bookshelfFixture('empty')).toEqual([])
  })

  it('single scenario mirrors the Catalog seed', () => {
    expect(bookshelfFixture('single')).toEqual([
      {
        title: 'Atomic Habits',
        author: 'James Clear',
        format: 'epub',
        dateLabel: '0秒後',
        progression: 0,
        needsICloudDownload: true,
      },
    ])
  })

  it('populated scenario lists five books newest-first with snapshot date labels', () => {
    const books = bookshelfFixture('populated')
    expect(books.map((b) => [b.title, b.format, b.dateLabel])).toEqual([
      ['Atomic Habits', 'epub', '0秒後'],
      ['Deep Work', 'pdf', '2天前'],
      ['Flow', 'epub', '5天前'],
      ['Meditations', 'txt', '1週前'],
      ['On Writing Well', 'md', '2週前'],
    ])
    expect(books.map((b) => b.author)).toEqual([
      'James Clear',
      'Cal Newport',
      'Mihaly Csikszentmihalyi',
      'Marcus Aurelius',
      'William Zinsser',
    ])
  })
})
