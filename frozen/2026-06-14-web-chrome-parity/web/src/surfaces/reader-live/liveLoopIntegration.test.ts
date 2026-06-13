import { describe, expect, it } from 'vitest'
import { createApiClient, type ApiClient } from '../../api'
import {
  configPatchFromSettings,
  resolveBoundNotebookId,
  resolvedPanel,
  settingsFromConfig,
  withExplanation,
} from './liveLoop'

/**
 * 整合測試：把 Live Reader 取詞→翻譯→存詞→展開→刪除→設定持久化迴圈逐步打進
 * mock backend（createApiClient mode:'mock'），驗證 hook 實際送出的 client 呼叫
 * 與 response 形狀。不渲染 DOM（codebase 無 React renderer）；驗證的是 API 契約面。
 */
function authed(): ApiClient {
  return createApiClient({ mode: 'mock', getToken: () => 'mock-access-token' })
}

describe('live reader loop — translate → save → explain (mock backend)', () => {
  it('quick-translates a word and projects it into a panel', async () => {
    const api = authed()
    const res = await api.translate.quick({ word: 'chimes', context: 'the chimes rang' })
    expect(res.t).toBe('chimes 的翻譯')
    const panel = resolvedPanel('chimes', res)
    expect(panel.translation).toBe('chimes 的翻譯')
    expect(panel.word).toBe('chimes')
  })

  it('saves the translated word into the bound notebook', async () => {
    const api = authed()
    const res = await api.translate.quick({ word: 'serendipity' })
    const notebookId = resolveBoundNotebookId('classics', 'default')
    const add = await api.vocabulary.add(
      [{ word: 'serendipity', translation: res.t, context: 'ctx', root_form: res.r ?? null, source: 'reader' }],
      { notebookId },
    )
    expect(add.created).toBe(1)
  })

  it('falls back to the default notebook when the book is unbound', async () => {
    const api = authed()
    const notebookId = resolveBoundNotebookId(null, 'default')
    expect(notebookId).toBe('default')
    const add = await api.vocabulary.add(
      [{ word: 'flux', translation: 'x', context: '', source: 'reader' }],
      { notebookId },
    )
    expect(add.created).toBe(1)
  })

  it('triggers the pipeline after a save', async () => {
    const api = authed()
    const q = await api.pipeline.trigger('default')
    expect(q.status).toBe('queued')
  })

  it('lazily fetches the contextual explanation on expand', async () => {
    const api = authed()
    const tr = await api.translate.quick({ word: 'rang' })
    let panel = resolvedPanel('rang', tr)
    const ex = await api.translate.explain({ word: 'rang', context: 'the chimes rang' })
    panel = withExplanation(panel, ex)
    expect(panel.isExpanded).toBe(true)
    expect(panel.explanation).toBe('rang 在此語境中的說明。')
  })

  it('deletes a saved word from the bound notebook', async () => {
    const api = authed()
    // seed a known card the mock store carries (lifted from vocab fixtures).
    const cards = await api.vocabulary.list()
    expect(cards.length).toBeGreaterThan(0)
    const word = cards[0].content
    const del = await api.vocabulary.delete(word, { notebookId: 'default' })
    expect(del.deleted).toBe(word)
  })
})

describe('live reader settings persistence (mock backend)', () => {
  it('round-trips reader settings through PUT /api/user/config', async () => {
    const api = authed()
    const before = await api.user.config()
    const patch = configPatchFromSettings({ fontSize: 1.5, font: 'sans' }, 'dark', before.vocab_ui)
    const after = await api.user.updateConfig(patch)
    const { settings, theme } = settingsFromConfig(after)
    expect(settings.fontSize).toBe(1.5)
    expect(settings.font).toBe('sans')
    expect(theme).toBe('dark')
  })

  it('persists locator + progression via PUT position', async () => {
    const api = authed()
    const updated = await api.library.putPosition('book-1', {
      locator: 'epubcfi(/6/4!/4/2)',
      progression: 0.42,
      updated_at: new Date().toISOString(),
    })
    expect(updated.progression).toBe(0.42)
    expect(updated.locator).toBe('epubcfi(/6/4!/4/2)')
  })
})
