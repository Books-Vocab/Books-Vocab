import { describe, expect, it } from 'vitest'
import { SURFACE_SCENARIOS } from '../harness/scenarios'
import {
  currentScreen,
  initialNavState,
  pop,
  push,
  pushTargetFor,
  screenFor,
  selectTab,
  stackDepth,
} from './nav'

describe('initialNavState', () => {
  it('預設 tab = bookshelf，每個 surface-tab 預放 root 畫面', () => {
    const s = initialNavState()
    expect(s.tabId).toBe('bookshelf')
    // bookshelf + notebooks 是 surface-tab，各有單元素 stack
    expect(stackDepth(s)).toBe(1)
    expect(currentScreen(s)).toEqual({ surface: 'bookshelf', scenario: SURFACE_SCENARIOS.bookshelf[0] })
    expect(s.stacks.notebooks?.[0].surface).toBe('notebook')
    // overview 已是 surface-tab（統計儀表板）→ 預放 root 畫面
    expect(s.stacks.overview?.[0].surface).toBe('overview')
  })

  it('URL surface 命中 surface-tab → 選該 tab 並用 URL scenario 覆寫 root', () => {
    const s = initialNavState('notebook', 'single')
    expect(s.tabId).toBe('notebooks')
    expect(currentScreen(s)).toEqual({ surface: 'notebook', scenario: 'single' })
  })

  it('URL surface 非任何 surface-tab（如 reader）→ 落預設 bookshelf tab', () => {
    const s = initialNavState('reader', 'reading-compact')
    expect(s.tabId).toBe('bookshelf')
  })

  it('URL scenario 非該 surface 合法 taxonomy → 忽略，用預設 scenario', () => {
    const s = initialNavState('bookshelf', 'bogus')
    expect(currentScreen(s)).toEqual({ surface: 'bookshelf', scenario: SURFACE_SCENARIOS.bookshelf[0] })
  })
})

describe('selectTab', () => {
  it('切到另一個 surface-tab 保留各自 stack', () => {
    let s = initialNavState()
    s = push(s, screenFor('reader')) // bookshelf stack 深 2
    s = selectTab(s, 'notebooks')
    expect(s.tabId).toBe('notebooks')
    expect(stackDepth(s)).toBe(1)
    // 切回 bookshelf，深度 2 還在
    s = selectTab(s, 'bookshelf')
    expect(stackDepth(s)).toBe(2)
  })

  it('overview 已是 surface-tab → 可選並切換 tab', () => {
    const s = initialNavState()
    const next = selectTab(s, 'overview')
    expect(next.tabId).toBe('overview')
    expect(currentScreen(next)?.surface).toBe('overview')
  })

  it('未知 tab 不可選（no-op）', () => {
    const s = initialNavState()
    expect(selectTab(s, 'unknown')).toEqual(s)
  })
})

describe('push / pop', () => {
  it('push 加層、pop 退層，root 上 pop 為 no-op', () => {
    let s = initialNavState()
    s = push(s, screenFor('reader'))
    expect(stackDepth(s)).toBe(2)
    expect(currentScreen(s)?.surface).toBe('reader')
    s = pop(s)
    expect(stackDepth(s)).toBe(1)
    const atRoot = pop(s)
    expect(atRoot).toEqual(s) // root 上 pop 不變
  })
})

describe('pushTargetFor（誠實導航圖）', () => {
  it('bookshelf 點書 → reader', () => {
    expect(pushTargetFor(screenFor('bookshelf'), 'open-book')?.surface).toBe('reader')
  })
  it('notebook 點卡 → vocabulary，今日複習 → today-review', () => {
    expect(pushTargetFor(screenFor('notebook'), 'open-notebook')?.surface).toBe('vocabulary')
    expect(pushTargetFor(screenFor('notebook'), 'open-today-review')?.surface).toBe('today-review')
  })
  it('不匹配的 (surface, intent) → null', () => {
    expect(pushTargetFor(screenFor('bookshelf'), 'open-notebook')).toBeNull()
    expect(pushTargetFor(screenFor('reader'), 'open-book')).toBeNull()
  })
})
