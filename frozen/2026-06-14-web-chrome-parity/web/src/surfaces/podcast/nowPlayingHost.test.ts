import { describe, expect, it } from 'vitest'
import { createNowPlayingHostRegistry } from './nowPlayingHost'

// The persistent now-playing overlay is mounted by EVERY podcast surface (home /
// episode-list / player) so it survives surface remounts. But only ONE instance
// may render the bar at a time (else stacked duplicates). This registry elects a
// single active host: the most-recently-acquired token wins; on release it falls
// back to the previous holder.

describe('now-playing host registry (single-renderer election)', () => {
  it('elects the first acquirer', () => {
    const r = createNowPlayingHostRegistry()
    const a = r.acquire()
    expect(r.isActive(a)).toBe(true)
  })

  it('hands the crown to the latest acquirer (surface transition)', () => {
    const r = createNowPlayingHostRegistry()
    const a = r.acquire()
    const b = r.acquire()
    expect(r.isActive(a)).toBe(false)
    expect(r.isActive(b)).toBe(true)
  })

  it('falls back to the previous holder on release', () => {
    const r = createNowPlayingHostRegistry()
    const a = r.acquire()
    const b = r.acquire()
    r.release(b)
    expect(r.isActive(a)).toBe(true)
  })

  it('no active host once all released', () => {
    const r = createNowPlayingHostRegistry()
    const a = r.acquire()
    r.release(a)
    expect(r.isActive(a)).toBe(false)
    expect(r.active()).toBeNull()
  })

  it('notifies subscribers on election change', () => {
    const r = createNowPlayingHostRegistry()
    let n = 0
    const unsub = r.subscribe(() => (n += 1))
    const a = r.acquire()
    const b = r.acquire()
    r.release(b)
    unsub()
    r.release(a)
    expect(n).toBe(3) // acquire a, acquire b, release b → 3 elections; post-unsub silent
  })
})
