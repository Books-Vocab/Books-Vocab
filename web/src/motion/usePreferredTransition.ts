import { useReducedMotion } from 'framer-motion'
import type { Transition } from 'framer-motion'
import { reduced } from './springs'

/**
 * Resolve a motion `Transition` against the user's reduced-motion preference.
 *
 * framer-motion's `useReducedMotion()` reads the live `prefers-reduced-motion`
 * media query. When the user prefers reduced motion we collapse ANY requested
 * spring to the instant `reduced` transition (duration 0) — the state change
 * still happens, just without the slide/parallax/dim choreography.
 *
 * Every motion primitive in this folder routes its transition through this hook
 * so reduced-motion is honoured in one place (Step 4 of the foundation).
 */
export function usePreferredTransition(preferred: Transition): Transition {
  const prefersReduced = useReducedMotion()
  return prefersReduced ? reduced : preferred
}

export { useReducedMotion }
