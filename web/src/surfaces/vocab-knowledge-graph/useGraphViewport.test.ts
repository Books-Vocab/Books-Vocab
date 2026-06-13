import { describe, expect, it } from 'vitest'
import {
  IDENTITY_VIEWPORT,
  MAX_SCALE,
  MIN_SCALE,
  clampScale,
  clientToUser,
  panBy,
  screenDeltaToUser,
  zoomAround,
} from './useGraphViewport'

describe('clampScale', () => {
  it('keeps in-range values', () => {
    expect(clampScale(1)).toBe(1)
    expect(clampScale(2)).toBe(2)
  })
  it('clamps to [MIN_SCALE, MAX_SCALE]', () => {
    expect(clampScale(0.01)).toBe(MIN_SCALE)
    expect(clampScale(99)).toBe(MAX_SCALE)
  })
  it('falls back to MIN_SCALE on non-finite input', () => {
    expect(clampScale(NaN)).toBe(MIN_SCALE)
    expect(clampScale(Infinity)).toBe(MAX_SCALE)
  })
})

describe('panBy', () => {
  it('adds the delta to the translate, leaving scale untouched', () => {
    const vp = panBy({ tx: 10, ty: 20, scale: 2 }, 5, -3)
    expect(vp).toEqual({ tx: 15, ty: 17, scale: 2 })
  })
})

describe('zoomAround', () => {
  it('keeps the anchor world-point fixed on screen', () => {
    const vp = IDENTITY_VIEWPORT
    const ax = 100
    const ay = 50
    // world point under the anchor before zoom
    const wxBefore = (ax - vp.tx) / vp.scale
    const wyBefore = (ay - vp.ty) / vp.scale
    const z = zoomAround(vp, 2, ax, ay)
    // screen position of that same world point after zoom must equal the anchor
    expect(wxBefore * z.scale + z.tx).toBeCloseTo(ax)
    expect(wyBefore * z.scale + z.ty).toBeCloseTo(ay)
    expect(z.scale).toBe(2)
  })

  it('clamps the requested scale', () => {
    expect(zoomAround(IDENTITY_VIEWPORT, 999, 0, 0).scale).toBe(MAX_SCALE)
    expect(zoomAround(IDENTITY_VIEWPORT, 0.001, 0, 0).scale).toBe(MIN_SCALE)
  })

  it('is a no-op when the clamped scale is unchanged', () => {
    const vp = { tx: 3, ty: 4, scale: MAX_SCALE }
    expect(zoomAround(vp, 999, 10, 10)).toBe(vp)
  })
})

describe('screenDeltaToUser', () => {
  it('passes the delta through unchanged when the box is unmeasured', () => {
    expect(screenDeltaToUser(10, -5, 0, 0, 360, 560)).toEqual({ dx: 10, dy: -5 })
  })

  it('scales a pixel delta into user units by the meet-scale inverse', () => {
    // client 720x1120 over a 360x560 viewBox → meet = min(2, 2) = 2 → user = px/2
    const { dx, dy } = screenDeltaToUser(20, 40, 720, 1120, 360, 560)
    expect(dx).toBeCloseTo(10)
    expect(dy).toBeCloseTo(20)
  })

  it('uses the limiting axis for non-uniform boxes (letterboxed)', () => {
    // client 360x1120 over 360x560 → meet = min(1, 2) = 1 → user = px
    const { dx, dy } = screenDeltaToUser(8, 8, 360, 1120, 360, 560)
    expect(dx).toBeCloseTo(8)
    expect(dy).toBeCloseTo(8)
  })
})

describe('clientToUser', () => {
  it('maps a point through the meet-scale and centre letterbox offset', () => {
    // client 720x1120 over 360x560 → s = 2, no letterbox (perfect 2x): user = px/2
    const { ax, ay } = clientToUser(360, 560, 720, 1120, 360, 560)
    expect(ax).toBeCloseTo(180)
    expect(ay).toBeCloseTo(280)
  })

  it('accounts for horizontal letterbox when the box is wider than the meet fit', () => {
    // client 1120x1120 over 360x560 → s = min(3.11, 2) = 2; drawn 720 wide,
    // offsetX = (1120-720)/2 = 200. point at px 200 → user 0; px 920 → user 360.
    expect(clientToUser(200, 0, 1120, 1120, 360, 560).ax).toBeCloseTo(0)
    expect(clientToUser(920, 0, 1120, 1120, 360, 560).ax).toBeCloseTo(360)
  })

  it('falls back to viewBox centre when the box is unmeasured', () => {
    expect(clientToUser(5, 5, 0, 0, 360, 560)).toEqual({ ax: 180, ay: 280 })
  })
})
