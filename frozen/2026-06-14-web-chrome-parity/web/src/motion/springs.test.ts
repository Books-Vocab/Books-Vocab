import { describe, expect, it } from 'vitest'
import { SPRINGS, gentle, navPush, reduced, sheet, snappy } from './springs'

/**
 * The springs are derived from SwiftUI `.spring(response:dampingFraction:)` via:
 *   stiffness = (2π / response)²
 *   damping   = 2 · ζ · (2π / response)   (mass = 1)
 * These tests pin the documented iOS source values → framer-motion params so a
 * future edit to one without the other is caught.
 */

function expectedSpring(response: number, zeta: number) {
  const omega0 = (Math.PI * 2) / response
  return {
    stiffness: Math.round(omega0 * omega0),
    damping: Math.round(2 * zeta * omega0 * 100) / 100,
    mass: 1,
  }
}

describe('iOS spring derivation', () => {
  it('navPush ← response 0.5, ζ 0.82', () => {
    const e = expectedSpring(0.5, 0.82)
    expect(navPush).toMatchObject({ type: 'spring', ...e })
    expect(e.stiffness).toBe(158)
  })

  it('sheet ← response 0.42, ζ 0.86 (snappier than navPush)', () => {
    expect(sheet).toMatchObject({ type: 'spring', ...expectedSpring(0.42, 0.86) })
    // snappier = higher stiffness than navPush
    expect((sheet as { stiffness: number }).stiffness).toBeGreaterThan(
      (navPush as { stiffness: number }).stiffness,
    )
  })

  it('snappy ← response 0.3, ζ 0.85', () => {
    expect(snappy).toMatchObject({ type: 'spring', ...expectedSpring(0.3, 0.85) })
  })

  it('gentle ← response 0.6, ζ 1.0 (critically damped, no overshoot)', () => {
    expect(gentle).toMatchObject({ type: 'spring', ...expectedSpring(0.6, 1.0) })
  })

  it('reduced transition is instant (duration 0, no spring)', () => {
    expect(reduced).toEqual({ duration: 0 })
  })

  it('SPRINGS table exposes every named preset', () => {
    expect(Object.keys(SPRINGS).sort()).toEqual(
      ['gentle', 'navPush', 'reduced', 'sheet', 'snappy'].sort(),
    )
  })
})
