import { describe, expect, it } from 'vitest'
import { SURFACE_SCENARIOS } from '../harness/scenarios'
import {
  currentScreen,
  initialNavState,
  isLiveReaderScreen,
  pop,
  push,
  pushTargetFor,
  routeKeyFor,
  screenFor,
  selectTab,
  stackDepth,
  type NavState,
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

  it('root 畫面 param-free（parity 相容：無 params 鍵）', () => {
    const s = initialNavState()
    const root = currentScreen(s)
    expect(root).not.toHaveProperty('params')
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

describe('screenFor', () => {
  it('無 params → param-free 畫面（不含 params 鍵）', () => {
    const s = screenFor('vocabulary')
    expect(s).toEqual({ surface: 'vocabulary', scenario: SURFACE_SCENARIOS.vocabulary[0] })
    expect(s).not.toHaveProperty('params')
  })

  it('帶 params → 攜帶實體 id', () => {
    const s = screenFor('vocabulary', { notebookId: 'nb-7' })
    expect(s.surface).toBe('vocabulary')
    expect(s.scenario).toBe(SURFACE_SCENARIOS.vocabulary[0])
    expect(s.params).toEqual({ notebookId: 'nb-7' })
  })
})

describe('routeKeyFor', () => {
  it('編碼 tabId:depth:surface（RouteTransition AnimatePresence 鍵）', () => {
    const s = initialNavState()
    expect(routeKeyFor(s)).toBe('bookshelf:1:bookshelf')
  })

  it('push 改變 depth → 鍵改變（觸發轉場）', () => {
    let s = initialNavState()
    const before = routeKeyFor(s)
    s = push(s, screenFor('reader'))
    const after = routeKeyFor(s)
    expect(after).toBe('bookshelf:2:reader')
    expect(after).not.toBe(before)
  })

  it('pop 還原鍵（pop 回前一畫面）', () => {
    let s = initialNavState()
    const root = routeKeyFor(s)
    s = push(s, screenFor('reader'))
    s = pop(s)
    expect(routeKeyFor(s)).toBe(root)
  })

  it('切 tab → 鍵改變（tabId 段不同）', () => {
    const s = initialNavState()
    const next = selectTab(s, 'notebooks')
    expect(routeKeyFor(next)).toBe('notebooks:1:notebook')
    expect(routeKeyFor(next)).not.toBe(routeKeyFor(s))
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

  it('push 攜帶 params 的畫面 → currentScreen 保留 params', () => {
    let s = initialNavState()
    s = push(s, screenFor('reader', { bookId: 'book-3' }))
    expect(currentScreen(s)?.params).toEqual({ bookId: 'book-3' })
  })
})

describe('isLiveReaderScreen（雙殼共用：掛 Live Reader 取代靜態 ReaderScreen）', () => {
  it('開書（bookshelf → reader push，深 2）→ true', () => {
    let s = initialNavState()
    s = push(s, screenFor('reader', { bookId: 'b1' }))
    expect(isLiveReaderScreen(s)).toBe(true)
  })

  it('reader 在 root（深 1）→ false（非點書開啟，不掛真閱讀器）', () => {
    // reader 不是 surface-tab，正常不會落 root；防禦性斷言 depth>1 條件。
    const s: NavState = {
      tabId: 'bookshelf',
      stacks: { bookshelf: [screenFor('reader')] },
    }
    expect(isLiveReaderScreen(s)).toBe(false)
  })

  it('深層但非 reader（如 bookshelf → settings）→ false', () => {
    let s = initialNavState()
    s = push(s, screenFor('settings'))
    expect(isLiveReaderScreen(s)).toBe(false)
  })

  it('bookshelf root（深 1）→ false', () => {
    expect(isLiveReaderScreen(initialNavState())).toBe(false)
  })

  it('pop 回書架後 → false（離開閱讀器卸載真渲染）', () => {
    let s = initialNavState()
    s = push(s, screenFor('reader', { bookId: 'b1' }))
    s = pop(s)
    expect(isLiveReaderScreen(s)).toBe(false)
  })
})

describe('pushTargetFor（誠實導航圖）', () => {
  describe('bookshelf', () => {
    it('點書 → reader，攜帶 bookId', () => {
      const t = pushTargetFor(screenFor('bookshelf'), 'open-book', { bookId: 'b1' })
      expect(t?.surface).toBe('reader')
      expect(t?.params).toEqual({ bookId: 'b1' })
    })
    it('無 params → reader（param-free，仍可達）', () => {
      const t = pushTargetFor(screenFor('bookshelf'), 'open-book')
      expect(t?.surface).toBe('reader')
      expect(t).not.toHaveProperty('params')
    })
    // PDF 書共用 reader-live route：點書 → reader screen（depth>1 → isLiveReaderScreen
    // true → 掛 LiveReaderScreen）。format flag 由 params 攜帶，reader-live Phase-2
    // agent 依 params.format==='pdf' 切 pdfjs-dist 引擎，否則 epub.js。共用同一 push
    // target/route，不另開 surface。
    it('點 PDF 書 → reader，params 攜帶 format=pdf（共用 reader-live route）', () => {
      const t = pushTargetFor(screenFor('bookshelf'), 'open-book', {
        bookId: 'book-2',
        format: 'pdf',
      })
      expect(t?.surface).toBe('reader')
      expect(t?.params).toEqual({ bookId: 'book-2', format: 'pdf' })
    })
    it('gear → settings（設定子樹入口）', () => {
      expect(pushTargetFor(screenFor('bookshelf'), 'open-settings')?.surface).toBe('settings')
    })
  })

  describe('notebook', () => {
    it('點卡 → vocabulary，攜帶 notebookId', () => {
      const t = pushTargetFor(screenFor('notebook'), 'open-notebook', { notebookId: 'nb-2' })
      expect(t?.surface).toBe('vocabulary')
      expect(t?.params).toEqual({ notebookId: 'nb-2' })
    })
    it('今日複習 → today-review', () => {
      expect(pushTargetFor(screenFor('notebook'), 'open-today-review')?.surface).toBe('today-review')
    })
    it('編輯 → notebook-edit，攜帶 notebookId', () => {
      const t = pushTargetFor(screenFor('notebook'), 'edit-notebook', { notebookId: 'nb-5' })
      expect(t?.surface).toBe('notebook-edit')
      expect(t?.params).toEqual({ notebookId: 'nb-5' })
    })
  })

  describe('vocabulary', () => {
    it('點單字列 → word-detail-sheet，攜帶 word', () => {
      const t = pushTargetFor(screenFor('vocabulary'), 'open-word', { word: 'serendipity' })
      expect(t?.surface).toBe('word-detail-sheet')
      expect(t?.params).toEqual({ word: 'serendipity' })
    })
    // 今日複習 bar（vocabulary header 上方）→ today-review 複習卡。iOS
    // VocabularyView 的 review CTA bar 在單字本內，故 vocabulary 也須有此邊（桌面
    // ?shell=1 點今日複習曾因缺此邊回傳 null → no-op 的根因）。
    it('今日複習 → today-review（vocab review bar 入口；修桌面 no-op）', () => {
      expect(pushTargetFor(screenFor('vocabulary'), 'open-today-review')?.surface).toBe(
        'today-review',
      )
    })
    it('今日複習 target param-free（today-review 不依實體 id）', () => {
      const t = pushTargetFor(screenFor('vocabulary'), 'open-today-review')
      expect(t).not.toHaveProperty('params')
    })
    it('新增連結 → vocab-add-link', () => {
      expect(pushTargetFor(screenFor('vocabulary'), 'add-link')?.surface).toBe('vocab-add-link')
    })
    it('知識圖譜 → knowledge-graph-view', () => {
      expect(pushTargetFor(screenFor('vocabulary'), 'open-knowledge-graph')?.surface).toBe(
        'knowledge-graph-view',
      )
    })
    it('知識圖譜（live force graph）→ vocab-knowledge-graph', () => {
      expect(
        pushTargetFor(screenFor('vocabulary'), 'open-vocab-knowledge-graph')?.surface,
      ).toBe('vocab-knowledge-graph')
    })
  })

  describe('word-detail-sheet', () => {
    // iOS WordDetailPresenter.linksSection 的「知識連結」plus 鈕（onAddLink）→ 新增
    // 連結 sheet。word-detail 是 vocabulary 點單字列 push 進來的詳情層，其內仍可
    // 再下鑽新增連結，故導航圖須有 word-detail-sheet → vocab-add-link 邊。
    it('知識連結 plus → vocab-add-link，攜帶 word（接力被檢視單字）', () => {
      const t = pushTargetFor(screenFor('word-detail-sheet'), 'add-link', { word: 'lucid' })
      expect(t?.surface).toBe('vocab-add-link')
      expect(t?.params).toEqual({ word: 'lucid' })
    })
    it('無 params → vocab-add-link（param-free，仍可達）', () => {
      const t = pushTargetFor(screenFor('word-detail-sheet'), 'add-link')
      expect(t?.surface).toBe('vocab-add-link')
      expect(t).not.toHaveProperty('params')
    })
  })

  describe('podcast', () => {
    it('podcast-home 點系列 → podcast-episode-list，攜帶 seriesId', () => {
      const t = pushTargetFor(screenFor('podcast-home'), 'open-podcast-series', { seriesId: 's9' })
      expect(t?.surface).toBe('podcast-episode-list')
      expect(t?.params).toEqual({ seriesId: 's9' })
    })
    it('episode-list 點集數 → podcast（player），攜帶 seriesId/epNum', () => {
      const t = pushTargetFor(screenFor('podcast-episode-list'), 'open-podcast-episode', {
        seriesId: 's9',
        epNum: 3,
      })
      expect(t?.surface).toBe('podcast')
      expect(t?.params).toEqual({ seriesId: 's9', epNum: 3 })
    })
  })

  describe('settings', () => {
    it('複習設定 → settings-review', () => {
      expect(pushTargetFor(screenFor('settings'), 'open-settings-review')?.surface).toBe(
        'settings-review',
      )
    })
    it('訂閱 → settings-subscription', () => {
      expect(pushTargetFor(screenFor('settings'), 'open-settings-subscription')?.surface).toBe(
        'settings-subscription',
      )
    })
    it('帳號 → settings-account-detail', () => {
      expect(pushTargetFor(screenFor('settings'), 'open-settings-account')?.surface).toBe(
        'settings-account-detail',
      )
    })
    it('翻譯語言 → translation-language-settings', () => {
      expect(
        pushTargetFor(screenFor('settings'), 'open-settings-translation-language')?.surface,
      ).toBe('translation-language-settings')
    })
    it('同步狀態 → sync', () => {
      expect(pushTargetFor(screenFor('settings'), 'open-sync')?.surface).toBe('sync')
    })
  })

  describe('不匹配', () => {
    it('不匹配的 (surface, intent) → null', () => {
      expect(pushTargetFor(screenFor('bookshelf'), 'open-notebook')).toBeNull()
      expect(pushTargetFor(screenFor('reader'), 'open-book')).toBeNull()
      expect(pushTargetFor(screenFor('vocabulary'), 'open-book')).toBeNull()
      expect(pushTargetFor(screenFor('overview'), 'open-knowledge-graph')).toBeNull()
      // word-detail-sheet 只接 add-link，其餘 intent 不匹配。
      expect(pushTargetFor(screenFor('word-detail-sheet'), 'open-word')).toBeNull()
    })
  })
})
