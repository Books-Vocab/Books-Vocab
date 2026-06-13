import { useRef } from 'react'
import { useDrag } from '@use-gesture/react'

/**
 * useSwipeBack — iOS interactive "swipe from the left edge to go back".
 *
 * Mirrors UINavigationController's interactivePopGestureRecognizer: a drag that
 * STARTS within the left screen edge and pulls rightward past a distance/velocity
 * threshold pops the nav stack. Intended for the mobile AppShell stack only.
 *
 * Design:
 *   • Edge-gated: the gesture only arms if the touch started within
 *     `edgeWidth` px of the left edge (default 24, matching iOS's edge zone).
 *   • Direction-gated: only rightward drags (positive x) count; vertical scroll
 *     and leftward drags are ignored so it never fights list scrolling.
 *   • Threshold: fires `onBack` once when either the drag distance exceeds
 *     `distance` px OR a fast right-flick exceeds the velocity threshold.
 *   • `enabled` (default true): pass `false` on desktop/tablet so it never fires
 *     there — the caller wires this to the mobile breakpoint / canGoBack.
 *   • pointer="touch": bind to touch only, so mouse drags on desktop don't pop.
 *
 * Returns a bind() to spread onto the stack container:
 *   const bind = useSwipeBack({ onBack: pop, enabled: isMobile && canGoBack })
 *   <div {...bind()} className="…stack…">…</div>
 *
 * PARITY ISOLATION: only wired into AppShell (shell path). The parity capture
 * path never mounts AppShell's interactive container, so capture is untouched.
 */
export function useSwipeBack({
  onBack,
  enabled = true,
  edgeWidth = 24,
  distance = 70,
  velocity = 0.4,
}: {
  /** Called once when a qualifying edge-swipe completes. */
  onBack: () => void
  /** When false the gesture is fully inert (e.g. desktop / at root). */
  enabled?: boolean
  /** Left-edge zone (px) a drag must start within to arm. */
  edgeWidth?: number
  /** Min rightward travel (px) to trigger a pop on release. */
  distance?: number
  /** Min rightward velocity (px/ms) for a flick-to-pop. */
  velocity?: number
}) {
  // Latch so a single drag can only pop once even if both thresholds are met.
  const firedRef = useRef(false)

  return useDrag(
    (state) => {
      const {
        first,
        last,
        movement: [mx],
        velocity: [vx],
        direction: [dx],
        initial: [ix],
      } = state

      if (!enabled) return

      // Arm only when the gesture began inside the left edge zone.
      if (first) {
        firedRef.current = false
        if (ix > edgeWidth) {
          state.cancel?.()
          return
        }
      }

      // Ignore leftward movement (dx < 0) — back is a rightward pull.
      if (firedRef.current || dx < 0) return

      const farEnough = mx > distance
      const fastEnough = vx > velocity && dx > 0
      if ((last && farEnough) || fastEnough) {
        firedRef.current = true
        onBack()
      }
    },
    {
      enabled,
      axis: 'x',
      pointer: { touch: true },
      // Don't hijack vertical scroll: only horizontal intent counts.
      filterTaps: true,
    },
  )
}
