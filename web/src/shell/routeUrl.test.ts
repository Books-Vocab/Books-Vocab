import { describe, expect, it } from 'vitest'
import { initialNavState, push, screenFor, selectTab } from './nav'
import { navToPath, pathToNav } from './routeUrl'

describe('navToPath', () => {
  it('root bookshelf → /app/bookshelf', () => {
    expect(navToPath(initialNavState())).toBe('/app/bookshelf')
  })

  it('選 notebooks tab（root surface=notebook）→ /app/notebook', () => {
    const s = selectTab(initialNavState(), 'notebooks')
    expect(navToPath(s)).toBe('/app/notebook')
  })

  it('push 帶單一 param 的畫面', () => {
    let s = selectTab(initialNavState(), 'notebooks')
    s = push(s, screenFor('vocabulary', { notebookId: 'nb-5' }))
    expect(navToPath(s)).toBe('/app/notebook/vocabulary~notebookId:nb-5')
  })

  it('深層 stack + 多 param（固定 key 順序）', () => {
    let s = selectTab(initialNavState(), 'podcasts')
    s = push(s, screenFor('podcast-episode-list', { seriesId: 's1' }))
    s = push(s, screenFor('podcast', { seriesId: 's1', epNum: 3 }))
    expect(navToPath(s)).toBe(
      '/app/podcast-home/podcast-episode-list~seriesId:s1/podcast~seriesId:s1,epNum:3',
    )
  })

  it('非預設 scenario 用 @ 編碼（root override）', () => {
    const s = initialNavState('notebook', 'single')
    expect(navToPath(s)).toBe('/app/notebook@single')
  })

  it('param value 做 URL 編碼（含 / 空白 :）', () => {
    let s = selectTab(initialNavState(), 'notebooks')
    s = push(s, screenFor('vocabulary', { notebookId: 'nb-1' }))
    s = push(s, screenFor('word-detail-sheet', { word: 'a/b c' }))
    expect(navToPath(s)).toBe(
      '/app/notebook/vocabulary~notebookId:nb-1/word-detail-sheet~word:a%2Fb%20c',
    )
  })
})

describe('pathToNav', () => {
  it('round-trip：選 tab', () => {
    const s = selectTab(initialNavState(), 'notebooks')
    expect(pathToNav(navToPath(s))).toEqual(s)
  })

  it('round-trip：深層帶 params', () => {
    let s = selectTab(initialNavState(), 'notebooks')
    s = push(s, screenFor('vocabulary', { notebookId: 'nb-5' }))
    s = push(s, screenFor('word-detail-sheet', { word: 'serendipity' }))
    expect(pathToNav(navToPath(s))).toEqual(s)
  })

  it('round-trip：epNum 還原為 number 非 string', () => {
    let s = selectTab(initialNavState(), 'podcasts')
    s = push(s, screenFor('podcast', { seriesId: 's1', epNum: 3 }))
    const back = pathToNav(navToPath(s))
    expect(back).toEqual(s)
    expect(back?.stacks.podcasts?.[1]?.params?.epNum).toBe(3)
  })

  it('round-trip：非預設 root scenario', () => {
    const s = initialNavState('notebook', 'single')
    expect(pathToNav(navToPath(s))).toEqual(s)
  })

  it('round-trip：param value 含特殊字元', () => {
    let s = selectTab(initialNavState(), 'notebooks')
    s = push(s, screenFor('vocabulary', { notebookId: 'nb-1' }))
    s = push(s, screenFor('word-detail-sheet', { word: 'a/b c' }))
    expect(pathToNav(navToPath(s))).toEqual(s)
  })

  it('容忍尾斜線', () => {
    expect(pathToNav('/app/notebook/')).toEqual(selectTab(initialNavState(), 'notebooks'))
  })

  it('非 /app 路徑 → null', () => {
    expect(pathToNav('/notebook')).toBeNull()
    expect(pathToNav('/')).toBeNull()
    expect(pathToNav('')).toBeNull()
  })

  it('/app 無 tab seg → null', () => {
    expect(pathToNav('/app')).toBeNull()
    expect(pathToNav('/app/')).toBeNull()
  })

  it('未知 surface → null', () => {
    expect(pathToNav('/app/bogus')).toBeNull()
  })

  it('seg0 surface 非 tab root（vocabulary 不是 tab 入口）→ null', () => {
    expect(pathToNav('/app/vocabulary')).toBeNull()
  })

  it('非法 scenario → null', () => {
    expect(pathToNav('/app/notebook@nonsense')).toBeNull()
  })

  it('非法 pushed surface → null', () => {
    expect(pathToNav('/app/notebook/bogus')).toBeNull()
  })
})

describe('decode 嚴格性（P1.1-fix：禁止靜默 fallback）', () => {
  it('param 值含 ~ 被編碼為 %7E 且 round-trip', () => {
    let s = selectTab(initialNavState(), 'notebooks')
    s = push(s, screenFor('vocabulary', { notebookId: 'nb-1' }))
    s = push(s, screenFor('word-detail-sheet', { word: 'a~b' }))
    expect(navToPath(s)).toBe(
      '/app/notebook/vocabulary~notebookId:nb-1/word-detail-sheet~word:a%7Eb',
    )
    expect(pathToNav(navToPath(s))).toEqual(s)
  })

  it('format 合法值 round-trip', () => {
    let s = selectTab(initialNavState(), 'bookshelf')
    s = push(s, screenFor('reader', { bookId: 'bk-3', format: 'epub' }))
    expect(pathToNav(navToPath(s))).toEqual(s)
  })

  it('epNum 非非負整數字面 → null', () => {
    expect(pathToNav('/app/podcast-home/podcast~epNum:')).toBeNull()
    expect(pathToNav('/app/podcast-home/podcast~epNum:3.5')).toBeNull()
    expect(pathToNav('/app/podcast-home/podcast~epNum:0x10')).toBeNull()
    expect(pathToNav('/app/podcast-home/podcast~epNum:-1')).toBeNull()
    expect(pathToNav('/app/podcast-home/podcast~epNum:1e9')).toBeNull()
  })

  it('format 越域值 → null', () => {
    expect(pathToNav('/app/bookshelf/reader~format:zzz')).toBeNull()
  })

  it('未知 param key → null', () => {
    expect(pathToNav('/app/notebook/vocabulary~bogus:x')).toBeNull()
  })

  it('重複 param key → null', () => {
    expect(pathToNav('/app/notebook/vocabulary~notebookId:a,notebookId:b')).toBeNull()
  })

  it('空 ~（無 params）→ null', () => {
    expect(pathToNav('/app/notebook/vocabulary~')).toBeNull()
  })

  it('內部雙斜線 → null（尾斜線仍容忍）', () => {
    expect(pathToNav('/app//notebook')).toBeNull()
    expect(pathToNav('/app/notebook//vocabulary~notebookId:nb-1')).toBeNull()
    expect(pathToNav('/app/notebook/')).not.toBeNull()
  })
})
