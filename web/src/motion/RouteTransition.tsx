import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import type { Transition } from 'framer-motion'
import type { ReactNode } from 'react'
import { gentle, navPush, reduced as reducedTransition } from './springs'
import './motion.css'

/**
 * RouteTransition — the shared push/pop transition for the functional shell.
 *
 * This wraps the shell's *current* screen and animates the swap whenever the
 * navigation identity changes. It is driven entirely by two inputs from the nav
 * model (nav.ts):
 *   • routeKey  — a stable identity for the visible screen (surface + depth).
 *                 When it changes, AnimatePresence cross-fades old → new.
 *   • direction — 'push' | 'pop', so we know which way to slide.
 *
 * Two presentation modes (both iOS-faithful, isolated to the shell path):
 *
 *   mode="stack"  (mobile AppShell / tablet single-pane slide-over)
 *     UINavigationController feel: on PUSH the incoming screen slides in from
 *     the right (100% → 0) while the outgoing screen parallax-shifts LEFT (~30%
 *     of width, matching UIKit's parallax ratio) and DIMS. On POP it reverses.
 *     Both layers are absolutely stacked so they overlap during the transition.
 *
 *   mode="pane"   (desktop ResponsiveShell detail-pane swap)
 *     A softer, tasteful cross-fade + short slide WITHIN the content pane — not
 *     a full-screen push. Desktop already shows master+detail side by side, so a
 *     full slide would be wrong; this keeps the detail swap legible and calm.
 *
 * Reduced motion: when `prefers-reduced-motion` is set, the spring collapses to
 * an instant transition (usePreferredTransition) AND the slide offsets fall to
 * 0 — the new screen simply appears.
 *
 * PARITY ISOLATION: this component is only ever rendered from AppShell /
 * ResponsiveShell (the shell path). The parity capture path renders
 * PhoneFrame shell={false} → SurfaceView and never mounts it, so it cannot touch
 * the .phone-frame parity DOM or screenshots.
 */

export type RouteDirection = 'push' | 'pop'
export type RouteMode = 'stack' | 'pane'

/** UIKit parallax: the outgoing screen trails at ~30% of the incoming travel. */
const STACK_PARALLAX = 0.3
/** Desktop pane slide travel (px) — short and subtle, not a full-screen slide. */
const PANE_SLIDE_PX = 24

type Variants = {
  /** entering screen start state */
  initial: { x: string | number; opacity: number }
  /** settled state */
  animate: { x: string | number; opacity: number }
  /** exiting screen end state */
  exit: { x: string | number; opacity: number }
}

/**
 * Build the framer-motion variants for the given mode + direction. `reduced`
 * zeroes all spatial offsets so reduced-motion users get a plain swap.
 */
function variantsFor(
  mode: RouteMode,
  direction: RouteDirection,
  reduced: boolean,
): Variants {
  if (mode === 'pane') {
    const slide = reduced ? 0 : PANE_SLIDE_PX
    const into = direction === 'push' ? slide : -slide
    const out = direction === 'push' ? -slide : slide
    return {
      initial: { x: into, opacity: 0 },
      animate: { x: 0, opacity: 1 },
      exit: { x: out, opacity: 0 },
    }
  }
  // stack mode (full-screen iOS nav push/pop)
  if (reduced) {
    return {
      initial: { x: 0, opacity: 1 },
      animate: { x: 0, opacity: 1 },
      exit: { x: 0, opacity: 0 },
    }
  }
  if (direction === 'push') {
    // incoming from the right; outgoing parallax-left + dim.
    return {
      initial: { x: '100%', opacity: 1 },
      animate: { x: 0, opacity: 1 },
      exit: { x: `-${STACK_PARALLAX * 100}%`, opacity: 0.6 },
    }
  }
  // pop: incoming was parallax-left/dimmed; outgoing slides off to the right.
  return {
    initial: { x: `-${STACK_PARALLAX * 100}%`, opacity: 0.6 },
    animate: { x: 0, opacity: 1 },
    exit: { x: '100%', opacity: 1 },
  }
}

export function RouteTransition({
  routeKey,
  direction,
  mode = 'stack',
  className,
  children,
}: {
  /** Stable identity of the currently-visible screen (surface + depth). */
  routeKey: string
  /** Which way the nav moved to reach this screen. */
  direction: RouteDirection
  /** stack = full-screen iOS push; pane = desktop detail cross-fade. */
  mode?: RouteMode
  /** Class on the absolutely-positioned animated layer. */
  className?: string
  children: ReactNode
}) {
  const prefersReduced = useReducedMotion() ?? false
  const base: Transition = mode === 'pane' ? gentle : navPush
  // Reduced motion: instant transition AND zeroed spatial offsets (variantsFor).
  const transition: Transition = prefersReduced ? reducedTransition : base
  const v = variantsFor(mode, direction, prefersReduced)

  return (
    <div className={`route-transition route-transition--${mode}`}>
      {/* popLayout pops the exiting screen out of flow (framer-motion sets it
          absolute) so it overlaps the entering one only during the swap — no
          permanent absolute layer that would collapse pane height / kill scroll.
          initial={false} suppresses the mount animation on first paint. */}
      <AnimatePresence initial={false} mode="popLayout">
        <motion.div
          key={routeKey}
          className={className ? `route-layer ${className}` : 'route-layer'}
          initial={v.initial}
          animate={v.animate}
          exit={v.exit}
          transition={transition}
        >
          {children}
        </motion.div>
      </AnimatePresence>
    </div>
  )
}
