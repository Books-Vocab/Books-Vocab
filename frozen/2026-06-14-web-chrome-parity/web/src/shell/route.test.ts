import { describe, expect, it } from 'vitest'
import { screenFor } from './nav'
import { isAppPath, reachableStack, resolveShellRoute } from './route'

describe('isAppPath', () => {
  it('/app 與 /app/* 為真，其餘為假', () => {
    expect(isAppPath('/app')).toBe(true)
    expect(isAppPath('/app/notebook')).toBe(true)
    expect(isAppPath('/')).toBe(false)
    expect(isAppPath('/appfoo')).toBe(false)
    expect(isAppPath('/foo')).toBe(false)
  })
})

describe('reachableStack', () => {
  it('純 root（深度 1）→ 恆可達', () => {
    expect(reachableStack([screenFor('bookshelf')])).toBe(true)
  })

  it('合法邊 bookshelf→reader（open-book）→ 可達', () => {
    expect(reachableStack([screenFor('bookshelf'), screenFor('reader')])).toBe(true)
  })

  it('合法深層 notebook→vocabulary→word-detail-sheet → 可達', () => {
    expect(
      reachableStack([
        screenFor('notebook'),
        screenFor('vocabulary'),
        screenFor('word-detail-sheet'),
      ]),
    ).toBe(true)
  })

  it('無此邊 notebook→paywall → 不可達', () => {
    expect(reachableStack([screenFor('notebook'), screenFor('paywall')])).toBe(false)
  })

  it('無此邊 bookshelf→vocabulary → 不可達', () => {
    expect(reachableStack([screenFor('bookshelf'), screenFor('vocabulary')])).toBe(false)
  })
})

describe('resolveShellRoute', () => {
  it('非 /app → nonShell', () => {
    expect(resolveShellRoute('/')).toEqual({ kind: 'nonShell' })
    expect(resolveShellRoute('/foo')).toEqual({ kind: 'nonShell' })
  })

  it('合法 /app 路徑 → valid + nav', () => {
    const r = resolveShellRoute('/app/notebook')
    expect(r.kind).toBe('valid')
    if (r.kind === 'valid') expect(r.nav.tabId).toBe('notebooks')
  })

  it('合法深層可達 → valid', () => {
    expect(resolveShellRoute('/app/notebook/vocabulary~notebookId:nb-5').kind).toBe('valid')
  })

  it('codec 不合法 → notFound', () => {
    expect(resolveShellRoute('/app/bogus')).toEqual({ kind: 'notFound' })
    expect(resolveShellRoute('/app/notebook/bogus')).toEqual({ kind: 'notFound' })
    expect(resolveShellRoute('/app/vocabulary')).toEqual({ kind: 'notFound' }) // seg0 非 tab root
  })

  it('codec 合法但 nav-graph 不可達 → notFound', () => {
    expect(resolveShellRoute('/app/notebook/paywall')).toEqual({ kind: 'notFound' })
  })
})
