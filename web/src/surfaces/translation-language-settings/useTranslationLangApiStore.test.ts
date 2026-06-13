import { describe, expect, it } from 'vitest'
import {
  DEFAULT_SOURCE_LANG,
  DEFAULT_TARGET_LANG,
  buildTranslationPatch,
  selectionFromConfig,
} from './useTranslationLangApiStore'
import type { UserConfigResponse } from '../../api/types'

function cfg(translation: Record<string, unknown> | null): UserConfigResponse {
  return { translation, review_clock: null, review_mode: null, vocab_ui: null, auto_link: null }
}

describe('selectionFromConfig', () => {
  it('projects source_lang / target_lang from the opaque translation group', () => {
    expect(selectionFromConfig(cfg({ source_lang: 'ja', target_lang: 'en', updated_at: 1 }))).toEqual({
      sourceId: 'ja',
      targetId: 'en',
    })
  })

  it('falls back to defaults when translation is null', () => {
    expect(selectionFromConfig(cfg(null))).toEqual({
      sourceId: DEFAULT_SOURCE_LANG,
      targetId: DEFAULT_TARGET_LANG,
    })
  })

  it('falls back to defaults when config is null', () => {
    expect(selectionFromConfig(null)).toEqual({
      sourceId: DEFAULT_SOURCE_LANG,
      targetId: DEFAULT_TARGET_LANG,
    })
  })

  it('rejects unsupported lang codes (source must be in the source set)', () => {
    // zh-Hant is a valid target but NOT a valid source → falls back to default source.
    expect(selectionFromConfig(cfg({ source_lang: 'zh-Hant', target_lang: 'ko' }))).toEqual({
      sourceId: DEFAULT_SOURCE_LANG,
      targetId: 'ko',
    })
  })

  it('rejects unsupported target code (de is a source-only lang)', () => {
    expect(selectionFromConfig(cfg({ source_lang: 'fr', target_lang: 'de' }))).toEqual({
      sourceId: 'fr',
      targetId: DEFAULT_TARGET_LANG,
    })
  })

  it('ignores non-string lang values', () => {
    expect(selectionFromConfig(cfg({ source_lang: 42, target_lang: null }))).toEqual({
      sourceId: DEFAULT_SOURCE_LANG,
      targetId: DEFAULT_TARGET_LANG,
    })
  })
})

describe('buildTranslationPatch', () => {
  it('assembles a single-group translation patch (no client timestamp)', () => {
    expect(buildTranslationPatch({ sourceId: 'fr', targetId: 'zh-Hans' })).toEqual({
      translation: { source_lang: 'fr', target_lang: 'zh-Hans', updated_at: null },
    })
  })
})
