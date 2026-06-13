import { useRef } from 'react'
import type { RouteDirection } from './RouteTransition'

/**
 * useNavDirection — derive push/pop from the nav stack depth across renders.
 *
 * The nav model (nav.ts) is a pure depth-carrying stack; it doesn't record which
 * way the last transition went. RouteTransition needs that to pick the slide
 * direction, so we infer it here: depth increased ⇒ 'push', decreased ⇒ 'pop'.
 * Equal depth (e.g. a same-depth tab switch or surface swap at the same level)
 * is treated as 'push' — a forward-feeling slide is the sensible default.
 *
 * We compare during render against a ref of the previous depth, updating the ref
 * each render. This is render-pure (no effect) so the direction is correct on
 * the very frame the swap happens, which is when AnimatePresence reads it.
 */
export function useNavDirection(depth: number): RouteDirection {
  const prevRef = useRef(depth)
  const prev = prevRef.current
  prevRef.current = depth
  return depth < prev ? 'pop' : 'push'
}
