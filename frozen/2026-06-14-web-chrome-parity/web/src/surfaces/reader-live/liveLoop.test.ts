import { describe, expect, it } from 'vitest'
import type { UserConfigResponse } from '../../api/types'
import {
  collapseExplanation,
  configPatchFromSettings,
  errorPanel,
  highlightCss,
  highlightWordSet,
  loadingPanel,
  markSaved,
  normalizeWord,
  resolveBoundNotebookId,
  resolvedPanel,
  settingsFromConfig,
  withExplanation,
  withExplanationError,
} from './liveLoop'

describe('liveLoop panel projections', () => {
  it('loading panel shows the word and a loading body', () => {
    const p = loadingPanel('serendipity')
    expect(p.word).toBe('serendipity')
    expect(p.isLoading).toBe(true)
    expect(p.translation).toBeNull()
    expect(p.isSaved).toBe(false)
  })

  it('resolved panel projects QuickTranslateResponse.t into translation', () => {
    const p = resolvedPanel('chimes', { t: '鐘聲', p: '/tʃaɪmz/', r: 'chime' })
    expect(p.translation).toBe('鐘聲')
    expect(p.isLoading).toBe(false)
    expect(p.translationError).toBeNull()
    expect(p.isSaved).toBe(false)
  })

  it('resolved panel can carry the saved flag', () => {
    const p = resolvedPanel('chimes', { t: '鐘聲' }, { isSaved: true })
    expect(p.isSaved).toBe(true)
  })

  it('error panel surfaces the message as translationError', () => {
    const p = errorPanel('rang', '額度已用完')
    expect(p.translationError).toBe('額度已用完')
    expect(p.translation).toBeNull()
    expect(p.isLoading).toBe(false)
  })

  it('withExplanation expands and fills explanation from ExplainResponse.e', () => {
    const base = resolvedPanel('chimes', { t: '鐘聲' })
    const expanded = withExplanation(base, { e: '一組調音鐘的聲響' })
    expect(expanded.isExpanded).toBe(true)
    expect(expanded.explanation).toBe('一組調音鐘的聲響')
    expect(expanded.explanationError).toBeNull()
    // translation preserved
    expect(expanded.translation).toBe('鐘聲')
  })

  it('withExplanationError keeps expanded and surfaces error', () => {
    const base = resolvedPanel('chimes', { t: '鐘聲' })
    const errd = withExplanationError(base, '解釋失敗')
    expect(errd.isExpanded).toBe(true)
    expect(errd.explanationError).toBe('解釋失敗')
  })

  it('collapseExplanation collapses without losing data', () => {
    const base = withExplanation(resolvedPanel('chimes', { t: '鐘聲' }), { e: 'x' })
    const collapsed = collapseExplanation(base)
    expect(collapsed.isExpanded).toBe(false)
    expect(collapsed.explanation).toBe('x')
  })

  it('markSaved flips the saved flag', () => {
    expect(markSaved(resolvedPanel('w', { t: 't' })).isSaved).toBe(true)
  })
})

describe('liveLoop notebook binding (iOS book.resolvedNotebookId parity)', () => {
  it('prefers the bound notebook id', () => {
    expect(resolveBoundNotebookId('classics', 'default')).toBe('classics')
  })
  it('falls back to default when unbound', () => {
    expect(resolveBoundNotebookId(null, 'default')).toBe('default')
    expect(resolveBoundNotebookId(undefined, 'default')).toBe('default')
  })
})

describe('liveLoop highlight', () => {
  it('normalizes words (lowercase, strip edge punctuation)', () => {
    expect(normalizeWord("Chimes'")).toBe('chimes')
    expect(normalizeWord('-Rang-')).toBe('rang')
  })

  it('builds a highlight word set, dropping sub-2-char noise', () => {
    const set = highlightWordSet(['Chimes', 'a', 'Rang', "rang'"])
    expect(set.has('chimes')).toBe(true)
    expect(set.has('rang')).toBe(true)
    expect(set.has('a')).toBe(false)
    // dedupe: rang appears once
    expect(set.size).toBe(2)
  })

  it('highlight CSS targets the kg-vocab-hl mark class', () => {
    const css = highlightCss()
    expect(css).toContain('mark.kg-vocab-hl')
    expect(css).toContain('background')
  })
})

describe('liveLoop settings <-> user config', () => {
  it('returns defaults from empty/missing config', () => {
    const { settings, theme } = settingsFromConfig(null)
    expect(settings.fontSize).toBe(1.0)
    expect(settings.font).toBe('serif')
    expect(theme).toBe('paper')
  })

  it('reads reader settings out of vocab_ui.reader', () => {
    const config = {
      vocab_ui: { reader: { fontSize: 1.5, font: 'sans', theme: 'dark' } },
    } as unknown as UserConfigResponse
    const { settings, theme } = settingsFromConfig(config)
    expect(settings.fontSize).toBe(1.5)
    expect(settings.font).toBe('sans')
    expect(theme).toBe('dark')
  })

  it('clamps out-of-range / invalid persisted values to defaults', () => {
    const config = {
      vocab_ui: { reader: { fontSize: 99, font: 'wingdings', theme: 'neon' } },
    } as unknown as UserConfigResponse
    const { settings, theme } = settingsFromConfig(config)
    expect(settings.fontSize).toBe(1.0)
    expect(settings.font).toBe('serif')
    expect(theme).toBe('paper')
  })

  it('round-trips settings through a config patch', () => {
    const patch = configPatchFromSettings({ fontSize: 1.25, font: 'sans' }, 'dark', null)
    const restored = settingsFromConfig({ vocab_ui: patch.vocab_ui } as UserConfigResponse)
    expect(restored.settings.fontSize).toBe(1.25)
    expect(restored.settings.font).toBe('sans')
    expect(restored.theme).toBe('dark')
  })

  it('config patch preserves other vocab_ui keys (LWW merge)', () => {
    const patch = configPatchFromSettings({ fontSize: 1.0, font: 'serif' }, 'paper', {
      someOtherKey: 'keep-me',
    } as unknown as UserConfigResponse['vocab_ui'])
    expect((patch.vocab_ui as Record<string, unknown>).someOtherKey).toBe('keep-me')
    expect((patch.vocab_ui as Record<string, unknown>).reader).toBeTruthy()
  })
})
