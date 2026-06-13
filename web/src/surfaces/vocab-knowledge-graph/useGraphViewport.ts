// Pan/zoom viewport math for the force-graph canvas — pure + testable.
//
// The SVG renders the simulation in a fixed viewBox (cw×ch). Pan/zoom is applied
// as an SVG-space transform on a wrapper <g>: `translate(tx ty) scale(scale)`.
// Keeping the transform IN SVG-USER-SPACE (not CSS px) means it composes cleanly
// with `preserveAspectRatio` and stays resolution-independent.
//
// Every function here is PURE (no React, no DOM) so the clamp/anchor math is unit
// testable and the gesture handlers in ForceGraphCanvas stay thin.

/** A 2D affine viewport: world → screen is `p' = p * scale + (tx, ty)`. */
export interface Viewport {
  /** translate X, in SVG user units. */
  tx: number
  /** translate Y, in SVG user units. */
  ty: number
  /** uniform zoom factor (1 = fit). */
  scale: number
}

export const IDENTITY_VIEWPORT: Viewport = { tx: 0, ty: 0, scale: 1 }

/** Zoom limits — wide enough to inspect a cluster, bounded so it can't invert/vanish. */
export const MIN_SCALE = 0.4
export const MAX_SCALE = 4

function clamp(v: number, lo: number, hi: number): number {
  // NaN → lo (safe floor); ±Infinity clamp naturally to hi/lo via Math.min/max.
  if (Number.isNaN(v)) return lo
  return Math.max(lo, Math.min(hi, v))
}

/** Clamp a raw zoom factor into [MIN_SCALE, MAX_SCALE]. */
export function clampScale(scale: number): number {
  return clamp(scale, MIN_SCALE, MAX_SCALE)
}

/**
 * Apply a pan delta (already converted to SVG user units) to the viewport.
 * Pan is unconstrained on purpose: the graph is a free canvas and over-pan just
 * scrolls empty space, which the next drag / reset recovers.
 */
export function panBy(vp: Viewport, dx: number, dy: number): Viewport {
  return { ...vp, tx: vp.tx + dx, ty: vp.ty + dy }
}

/**
 * Zoom toward an anchor point so the world point under the cursor stays put
 * (the natural "zoom where you point" feel).
 *
 * Screen point S maps from world point W by S = W*scale + t. To keep S fixed
 * while scale changes (s → s'), solve for the new translate:
 *   t' = S - W*s'  where  W = (S - t) / s
 *      = S - ((S - t)/s) * s'
 *
 * @param ax,ay anchor in SVG user-space (the same space tx/ty live in).
 */
export function zoomAround(vp: Viewport, nextScaleRaw: number, ax: number, ay: number): Viewport {
  const s = vp.scale
  const sNext = clampScale(nextScaleRaw)
  if (sNext === s) return vp
  const wx = (ax - vp.tx) / s
  const wy = (ay - vp.ty) / s
  return {
    scale: sNext,
    tx: ax - wx * sNext,
    ty: ay - wy * sNext,
  }
}

/**
 * Convert a screen-pixel delta into an SVG-user-unit delta.
 *
 * The SVG is laid out at `clientW × clientH` CSS px but draws in a `cw × ch`
 * user-space viewBox with `preserveAspectRatio: xMidYMid meet` (uniform scale,
 * letterboxed). The user-per-pixel factor is therefore the SINGLE meet-scale
 * `min(cw/clientW, ch/clientH)` inverted — i.e. user units per CSS px =
 * `1 / meetScale` where meetScale = min(clientW/cw, clientH/ch).
 *
 * Returns the original delta unchanged when the client box is unmeasured (0),
 * so first-frame gestures degrade gracefully instead of producing NaN.
 */
export function screenDeltaToUser(
  dxPx: number,
  dyPx: number,
  clientW: number,
  clientH: number,
  cw: number,
  ch: number,
): { dx: number; dy: number } {
  if (!(clientW > 0) || !(clientH > 0) || !(cw > 0) || !(ch > 0)) {
    return { dx: dxPx, dy: dyPx }
  }
  const meet = Math.min(clientW / cw, clientH / ch)
  if (!(meet > 0)) return { dx: dxPx, dy: dyPx }
  return { dx: dxPx / meet, dy: dyPx / meet }
}

/**
 * Convert an absolute client point (relative to the SVG box top-left) into the
 * SVG user-space coordinate, accounting for the `xMidYMid meet` letterbox offset.
 *
 * meet-scale s = min(clientW/cw, clientH/ch). The content is centred, so there's
 * a letterbox offset of `(clientW - cw*s)/2` / `(clientH - ch*s)/2`. The user
 * coordinate is `(pointPx - offset) / s`. Used as the zoom anchor for wheel/pinch
 * so zooming stays centred on the cursor, not the box origin.
 *
 * Falls back to centre-of-viewBox when the box is unmeasured so wheel zoom near
 * first paint still behaves (zoom toward middle).
 */
export function clientToUser(
  pxX: number,
  pxY: number,
  clientW: number,
  clientH: number,
  cw: number,
  ch: number,
): { ax: number; ay: number } {
  if (!(clientW > 0) || !(clientH > 0) || !(cw > 0) || !(ch > 0)) {
    return { ax: cw / 2, ay: ch / 2 }
  }
  const s = Math.min(clientW / cw, clientH / ch)
  if (!(s > 0)) return { ax: cw / 2, ay: ch / 2 }
  const offX = (clientW - cw * s) / 2
  const offY = (clientH - ch * s) / 2
  return { ax: (pxX - offX) / s, ay: (pxY - offY) / s }
}
