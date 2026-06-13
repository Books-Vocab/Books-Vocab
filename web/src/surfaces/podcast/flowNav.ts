// Inter-surface navigation for the shell-gated functional podcast flow:
//   home → episode-list(seriesId) → player(seriesId, epNum)
//
// The frozen shell nav (web/src/shell/nav.ts) is fixture-only: its `Screen` has
// no params, `pushTargetFor` has no podcast edges, and the podcasts tab routes
// straight to the player surface. Rather than edit the frozen shell (which would
// conflict with other streams and break the parity invariant), this module owns
// a small pure-function nav stack scoped to the podcast surface, carrying the
// seriesId / epNum params the iOS PodcastNavRoute (.series / .episode) needs.
//
// Pure functions, no React, no DOM.

/** A screen in the podcast flow stack. */
export type PodcastFlowScreen =
  | { route: 'home' }
  | { route: 'episode-list'; seriesId: string }
  | { route: 'player'; seriesId: string; epNum: number }

/** Non-empty stack; tail = current screen. */
export type PodcastFlowStack = readonly [PodcastFlowScreen, ...PodcastFlowScreen[]]

export const HOME: PodcastFlowScreen = { route: 'home' }

export function initialFlow(): PodcastFlowStack {
  return [HOME]
}

export function currentFlowScreen(stack: PodcastFlowStack): PodcastFlowScreen {
  return stack[stack.length - 1]
}

export function flowDepth(stack: PodcastFlowStack): number {
  return stack.length
}

/** Push the next screen (mirrors PodcastHomeView NavigationStack push). */
export function pushFlow(stack: PodcastFlowStack, screen: PodcastFlowScreen): PodcastFlowStack {
  return [...stack, screen] as unknown as PodcastFlowStack
}

/** Pop one level; no-op at root. */
export function popFlow(stack: PodcastFlowStack): PodcastFlowStack {
  if (stack.length <= 1) return stack
  return stack.slice(0, -1) as unknown as PodcastFlowStack
}

/** home → episode-list edge. */
export function openSeries(stack: PodcastFlowStack, seriesId: string): PodcastFlowStack {
  return pushFlow(stack, { route: 'episode-list', seriesId })
}

/** episode-list → player edge (also reachable from a continue-shelf rail card). */
export function openEpisode(
  stack: PodcastFlowStack,
  seriesId: string,
  epNum: number,
): PodcastFlowStack {
  return pushFlow(stack, { route: 'player', seriesId, epNum })
}
