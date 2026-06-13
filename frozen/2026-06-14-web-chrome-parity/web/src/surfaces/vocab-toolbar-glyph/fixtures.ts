import type { ScenarioId } from '../../harness/scenarios'

/**
 * VocabToolbarGlyph scenario fixtures — 對齊 VocabShellChromeScenarios.swift
 * 「Vocab Shell · Toolbar Glyph」3 態。systemImage 恆為 arrow.triangle.2.circlepath；
 * badge = nil（Plain）/ "5"（With badge）/ "99+"（Badge stress）。
 */
export const VOCAB_TOOLBAR_GLYPH_FIXTURES: Record<
  ScenarioId<'vocab-toolbar-glyph'>,
  { badge: string | null }
> = {
  plain: { badge: null },
  'with-badge': { badge: '5' },
  'badge-stress': { badge: '99+' },
}
