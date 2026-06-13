import type { Transition } from 'framer-motion'

/**
 * Shared "iOS feel" spring layer — the single source of motion timing for the
 * functional web shell. Every animated shell surface (route push/pop, sheets,
 * gestures) pulls its `transition` from here so the whole app shares one tuned
 * feel instead of each call site inventing its own numbers.
 *
 * ── Why springs, not durations ────────────────────────────────────────────
 * iOS animations (UIKit/SwiftUI) are spring-driven, characterised by two
 * physical params:
 *   • response (s)        — the natural period; "how long a full oscillation
 *                           would take". Lower = snappier.
 *   • dampingFraction (ζ) — 0..1; 1 = critically damped (no overshoot),
 *                           <1 = slight bounce.
 *
 * framer-motion's spring takes {stiffness (k), damping (c), mass (m)} instead.
 * The closed-form conversion from SwiftUI's `.spring(response:dampingFraction:)`
 * (mass fixed at 1) is:
 *
 *   ω0 = 2π / response                  (undamped natural angular frequency)
 *   k  = m · ω0²                        (stiffness)
 *   c  = 2 · dampingFraction · √(k·m)   (damping coefficient)
 *
 * With m = 1 this collapses to:
 *   stiffness = (2π / response)²
 *   damping   = 2 · ζ · (2π / response)
 *
 * The presets below are derived with that formula and the iOS source values are
 * documented inline so the mapping stays auditable.
 */

const TWO_PI = Math.PI * 2

/**
 * Derive framer-motion spring params from a SwiftUI-style spring spec.
 * mass is fixed at 1 to mirror SwiftUI's `.spring(response:dampingFraction:)`.
 */
function iosSpring(response: number, dampingFraction: number) {
  const omega0 = TWO_PI / response
  const stiffness = omega0 * omega0
  const damping = 2 * dampingFraction * omega0
  return {
    type: 'spring' as const,
    stiffness: Math.round(stiffness),
    damping: Math.round(damping * 100) / 100,
    mass: 1,
  }
}

/**
 * navPush — push/pop of a UINavigationController stack.
 * iOS source: the system interactive-pop / push driver feels like SwiftUI's
 * default `.spring(response: 0.5, dampingFraction: 0.82)` (no overshoot,
 * authoritative settle). This is the app's baseline "navigate" feel.
 *   → response 0.50s, ζ 0.82  ⇒  stiffness ≈ 158, damping ≈ 20.61
 */
export const navPush: Transition = iosSpring(0.5, 0.82)

/**
 * sheet — bottom-sheet present/dismiss. iOS sheets are slightly snappier than
 * navigation pushes (UISheetPresentationController detents settle fast and crisp),
 * with a hair of liveliness on present.
 * iOS source: `.spring(response: 0.42, dampingFraction: 0.86)`.
 *   → response 0.42s, ζ 0.86  ⇒  stiffness ≈ 224, damping ≈ 25.73
 */
export const sheet: Transition = iosSpring(0.42, 0.86)

/**
 * snappy — small, decisive UI changes (chips, toggles, selection, gesture
 * snap-back). Mirrors SwiftUI's `.snappy` ≈ `.spring(response: 0.3,
 * dampingFraction: 0.85)`.
 *   → response 0.30s, ζ 0.85  ⇒  stiffness ≈ 439, damping ≈ 35.61
 */
export const snappy: Transition = iosSpring(0.3, 0.85)

/**
 * gentle — soft, ambient transitions (cross-fades, desktop detail-pane swap,
 * dimming). Mirrors SwiftUI's `.smooth`-ish `.spring(response: 0.6,
 * dampingFraction: 1.0)` — critically damped, no bounce, unhurried.
 *   → response 0.60s, ζ 1.00  ⇒  stiffness ≈ 110, damping ≈ 20.94
 */
export const gentle: Transition = iosSpring(0.6, 1.0)

/**
 * reduced — the transition to use whenever `prefers-reduced-motion` is set.
 * Instant (duration 0): no spring, no slide — the change just happens. Pair
 * with framer-motion's `useReducedMotion()` (see `usePreferredTransition`).
 */
export const reduced: Transition = { duration: 0 }

/** Named preset table — handy for typed lookups / iteration. */
export const SPRINGS = { navPush, sheet, snappy, gentle, reduced } as const
export type SpringName = keyof typeof SPRINGS
