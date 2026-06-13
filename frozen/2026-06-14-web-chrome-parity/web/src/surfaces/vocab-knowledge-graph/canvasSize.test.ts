import { describe, expect, it } from 'vitest'
import { resolveCanvasSize } from './canvasSize'

// `resolveCanvasSize` is the pure decision the ResizeObserver-driven canvas makes:
// given the latest measured container box (which is 0×0 before the observer first
// fires, or in a node/SSR render) and the fixed fallback, pick the dimensions to
// drive the force simulation + SVG viewBox with. It must never hand the simulation
// a zero/degenerate box (that collapses every node onto the same point) and must
// prefer the real measured size once it is available.
describe('resolveCanvasSize', () => {
  it('uses the fallback when nothing has been measured yet (0×0 / SSR)', () => {
    expect(resolveCanvasSize(0, 0, 360, 560)).toEqual({ width: 360, height: 560 })
  })

  it('uses the real measured size once the observer reports it', () => {
    expect(resolveCanvasSize(900, 620, 360, 560)).toEqual({ width: 900, height: 620 })
  })

  it('falls back per-axis when only one dimension is degenerate', () => {
    expect(resolveCanvasSize(900, 0, 360, 560)).toEqual({ width: 900, height: 560 })
    expect(resolveCanvasSize(0, 620, 360, 560)).toEqual({ width: 360, height: 620 })
  })

  it('rounds sub-pixel measurements to integers (stable viewBox / layout)', () => {
    expect(resolveCanvasSize(899.6, 619.2, 360, 560)).toEqual({ width: 900, height: 619 })
  })

  it('ignores non-finite / negative measurements (defensive)', () => {
    expect(resolveCanvasSize(Number.NaN, -10, 360, 560)).toEqual({ width: 360, height: 560 })
    expect(resolveCanvasSize(Infinity, 620, 360, 560)).toEqual({ width: 360, height: 620 })
  })

  it('enforces a small minimum so the simulation never degenerates', () => {
    // A 1px sliver still produces a usable, non-collapsed layout box.
    const r = resolveCanvasSize(1, 1, 360, 560)
    expect(r.width).toBeGreaterThanOrEqual(2)
    expect(r.height).toBeGreaterThanOrEqual(2)
  })
})
