/**
 * Motion layer — the shared "iOS feel" primitives for the functional shell.
 *
 * Strictly shell-path only: none of these are mounted by the parity capture
 * path (PhoneFrame shell={false} → SurfaceView), so they cannot affect the
 * pixel fixtures. Surfaces adopt these incrementally; the foundation is wired
 * into AppShell (mobile) + ResponsiveShell (tablet/desktop) for push/pop.
 */
export {
  navPush,
  sheet,
  snappy,
  gentle,
  reduced,
  SPRINGS,
  type SpringName,
} from './springs'
export { usePreferredTransition, useReducedMotion } from './usePreferredTransition'
export {
  RouteTransition,
  type RouteDirection,
  type RouteMode,
} from './RouteTransition'
export { Sheet } from './Sheet'
export { useSwipeBack } from './useSwipeBack'
export { useNavDirection } from './useNavDirection'
