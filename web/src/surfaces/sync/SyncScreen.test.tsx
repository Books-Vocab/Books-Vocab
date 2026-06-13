// Screen-gate tests (node SSR, NO jsdom): prove the parity/fixture branch stays
// untouched and the ?shell=1 branch swaps in the live SyncApiStore.
//
// renderToStaticMarkup runs under node without a DOM. We stub globalThis.window
// to flip the shell gate (isShellMode reads window.location.search).

import { afterEach, describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { SyncScreen } from './SyncScreen'

const realWindow = (globalThis as { window?: unknown }).window

afterEach(() => {
  ;(globalThis as { window?: unknown }).window = realWindow
})

function setShell(on: boolean) {
  ;(globalThis as { window?: unknown }).window = {
    location: { search: on ? '?surface=sync&shell=1' : '?surface=sync' },
  }
}

describe('SyncScreen — parity (fixture) branch', () => {
  it('no ?shell → static fixture markup (no live store, static CTA)', () => {
    setShell(false)
    const html = renderToStaticMarkup(<SyncScreen scenario="ready" />)
    expect(html).not.toContain('data-live="1"')
    expect(html).toContain('開始同步')
    // fixture `ready` has the seeded pending words.
    expect(html).toContain('ineffable')
  })

  it('window absent (SSR/node) → fixture branch (gate defaults off)', () => {
    ;(globalThis as { window?: unknown }).window = undefined
    const html = renderToStaticMarkup(<SyncScreen scenario="ready" />)
    expect(html).not.toContain('data-live="1"')
    expect(html).toContain('開始同步')
  })
})

describe('SyncScreen — ?shell=1 live branch', () => {
  it('renders the coordinator-driven SyncApiStore', () => {
    setShell(true)
    const html = renderToStaticMarkup(<SyncScreen scenario="ready" />)
    expect(html).toContain('data-live="1"')
    // live store seeds the same ready-state mutations as the fixture.
    expect(html).toContain('開始同步')
    expect(html).toContain('ineffable')
    expect(html).toContain('ephemeral')
  })
})
