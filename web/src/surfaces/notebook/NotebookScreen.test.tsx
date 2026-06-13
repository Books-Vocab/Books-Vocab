// Screen-gate tests (node SSR, NO jsdom): prove the top "今日複習" CTA pill is
// reachable in the shell path while the parity/fixture branch stays bit-identical.
//
// renderToStaticMarkup runs under node without a DOM; it serializes the element
// tag + role/tabindex/aria but NOT onClick (no event system in SSR). We therefore
// assert the interactive affordance presence/absence in markup (mirrors the
// SyncScreen.test.tsx idiom: markup-presence proves the wiring branch). The pill
// going from a static <span> (no-op) to an AT-reachable <button> only when
// onOpenTodayReview is supplied is the behavioral contract that fixes the no-op.

import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { NotebookBody } from './NotebookScreen'
import { NOTEBOOK_FIXTURES } from './fixtures'

const fixture = NOTEBOOK_FIXTURES.single

/** Minimal store stub — only the surface NotebookBody touches at render time. */
function stubStore() {
  return {
    sheet: null,
    menuCardName: null,
    showFilter: false,
    openAdd: () => {},
    openEditFor: () => {},
    closeSheet: () => {},
    openMenu: () => {},
    closeMenu: () => {},
    addNotebook: () => {},
    renameNotebook: () => {},
    deleteNotebook: () => {},
  }
}

/** Extract the markup of the today-review CTA pill (the nb-pill-cta element). */
function ctaPillTag(html: string): string {
  // Match the opening tag of whatever element carries nb-pill-cta.
  const m = html.match(/<(\w+)[^>]*class="[^"]*nb-pill-cta[^"]*"[^>]*>/)
  return m ? m[0] : ''
}

describe('Notebook today-review pill — parity (fixture) branch', () => {
  it('renders as a plain non-interactive span (no button/role/tabindex)', () => {
    const html = renderToStaticMarkup(
      <NotebookBody cards={fixture.cards} store={stubStore()} reviewTotal={fixture.reviewTotal} />,
    )
    // CTA total still shown.
    expect(html).toContain(String(fixture.reviewTotal))
    const tag = ctaPillTag(html)
    // Pill stays a <span>, not a <button>; no interactive affordance leaks.
    expect(tag.startsWith('<span')).toBe(true)
    expect(tag).not.toContain('role="button"')
    expect(tag).not.toContain('tabindex')
  })
})

describe('Notebook today-review pill — shell branch (onOpenTodayReview wired)', () => {
  it('becomes an AT-reachable interactive element (no longer a no-op)', () => {
    const html = renderToStaticMarkup(
      <NotebookBody
        cards={fixture.cards}
        store={stubStore()}
        reviewTotal={fixture.reviewTotal}
        onOpenTodayReview={() => {}}
      />,
    )
    const tag = ctaPillTag(html)
    // Either a real <button> or a span carrying role="button" — AT/keyboard reachable.
    const reachable = tag.startsWith('<button') || tag.includes('role="button"')
    expect(reachable).toBe(true)
    // Carries an accessible name so screen readers announce the action.
    expect(tag).toContain('aria-label')
    // CTA total still shown.
    expect(html).toContain(String(fixture.reviewTotal))
  })
})
