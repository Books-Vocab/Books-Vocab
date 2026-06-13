// Pure size-resolution for the ResizeObserver-driven force-graph canvas.
//
// The force simulation + SVG viewBox must run in the canvas's REAL pixel space so
// the layout fills its container instead of being computed in a fixed 360×560
// virtual box and then scaled (which clusters nodes in a virtual top-left corner
// and visibly distorts on a wide content pane). The observer reports the live box;
// before it first fires (and in node/SSR renders) the box is 0×0, so we fall back
// per-axis to the fixed dimensions. Kept pure + integer-stable so the rendered
// DOM is reproducible and unit-testable without a DOM.

export interface CanvasSize {
  width: number
  height: number
}

// Floor below which a measured axis is treated as "not really measured" and the
// fallback is used instead — a 0/sub-pixel box would collapse the whole layout.
const MIN_AXIS_PX = 2

/** A finite, on-axis pixel measurement, else 0 (treated as "unmeasured"). */
function sanitizeAxis(measured: number): number {
  if (!Number.isFinite(measured) || measured <= 0) return 0
  return Math.round(measured)
}

/**
 * Resolve the dimensions the simulation/viewBox should use.
 *
 * @param measuredW latest observed container width (0 / NaN before first measure)
 * @param measuredH latest observed container height
 * @param fallbackW fixed width to use until/when no real width is available
 * @param fallbackH fixed height to use until/when no real height is available
 */
export function resolveCanvasSize(
  measuredW: number,
  measuredH: number,
  fallbackW: number,
  fallbackH: number,
): CanvasSize {
  const w = sanitizeAxis(measuredW) || Math.round(fallbackW)
  const h = sanitizeAxis(measuredH) || Math.round(fallbackH)
  return {
    width: Math.max(MIN_AXIS_PX, w),
    height: Math.max(MIN_AXIS_PX, h),
  }
}
