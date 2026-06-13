import { describe, expect, it } from 'vitest'
import { initialNavState, push, screenFor, selectTab } from './nav'
import { navToPath } from './routeUrl'
import { historySyncOp } from './historySync'

const bookshelf = initialNavState()
const notebooks = selectTab(initialNavState(), 'notebooks')
const deepNotebooks = push(
  selectTab(initialNavState(), 'notebooks'),
  screenFor('vocabulary', { notebookId: 'nb-5' }),
)

describe('historySyncOp', () => {
  it('URL 已與 nav 同步 → none（不製造重複 history entry）', () => {
    const op = historySyncOp({ nav: notebooks, currentPath: navToPath(notebooks), justEnabled: false })
    expect(op.kind).toBe('none')
  })

  it('穩態下 nav 改變（justEnabled=false，路徑不同）→ push', () => {
    const op = historySyncOp({ nav: deepNotebooks, currentPath: navToPath(notebooks), justEnabled: false })
    expect(op).toEqual({ kind: 'push', path: navToPath(deepNotebooks) })
  })

  it('剛 enable + URL 是另一個合法 /app 路徑 → adopt（URL 為真相，回該 NavState）', () => {
    const op = historySyncOp({ nav: bookshelf, currentPath: navToPath(deepNotebooks), justEnabled: true })
    expect(op).toEqual({ kind: 'adopt', path: navToPath(bookshelf), adopt: deepNotebooks })
  })

  it('剛 enable + URL 非 /app（legacy ?shell=1 在 "/"）→ replace（normalize 到 nav 路徑，不加 history entry）', () => {
    const op = historySyncOp({ nav: notebooks, currentPath: '/', justEnabled: true })
    expect(op).toEqual({ kind: 'replace', path: navToPath(notebooks) })
  })

  it('剛 enable + URL 是 /app 但 codec 不合法 → notFound（不靜默 normalize）', () => {
    const op = historySyncOp({ nav: notebooks, currentPath: '/app/bogus', justEnabled: true })
    expect(op).toEqual({ kind: 'notFound', path: navToPath(notebooks) })
  })

  it('剛 enable + URL 合法 surface 但 nav-graph 不可達 → notFound', () => {
    const op = historySyncOp({ nav: notebooks, currentPath: '/app/notebook/paywall', justEnabled: true })
    expect(op).toEqual({ kind: 'notFound', path: navToPath(notebooks) })
  })

  it('剛 enable + URL 已等於 nav 路徑 → none（即使 justEnabled）', () => {
    const op = historySyncOp({ nav: notebooks, currentPath: navToPath(notebooks), justEnabled: true })
    expect(op.kind).toBe('none')
  })
})
