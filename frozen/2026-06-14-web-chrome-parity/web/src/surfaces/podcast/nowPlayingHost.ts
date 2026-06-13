import { useEffect, useRef, useState } from 'react'

/**
 * Single-renderer election for the persistent now-playing overlay.
 *
 * Every podcast surface (home / episode-list / player) mounts the overlay host so
 * the mini-player + option sheets survive surface remounts. But exactly ONE host
 * may render the bar at any time, or transitions would stack duplicate bars. This
 * registry elects the most-recently-acquired token; on release it falls back to
 * the previous holder. During a push (new surface mounts before old unmounts) the
 * crown passes cleanly to the new host, then the old host releases harmlessly.
 *
 * A LIFO stack models this exactly: top of stack = active host.
 */
export interface NowPlayingHostRegistry {
  acquire(): symbol
  release(token: symbol): void
  isActive(token: symbol): boolean
  active(): symbol | null
  subscribe(fn: () => void): () => void
}

export function createNowPlayingHostRegistry(): NowPlayingHostRegistry {
  let stack: symbol[] = []
  const listeners = new Set<() => void>()

  const emit = () => {
    for (const fn of listeners) fn()
  }

  return {
    acquire() {
      const token = Symbol('nowplaying-host')
      stack.push(token)
      emit()
      return token
    },
    release(token) {
      const before = stack.length
      stack = stack.filter((t) => t !== token)
      if (stack.length !== before) emit()
    },
    isActive(token) {
      return stack.length > 0 && stack[stack.length - 1] === token
    },
    active() {
      return stack.length > 0 ? stack[stack.length - 1] : null
    },
    subscribe(fn) {
      listeners.add(fn)
      return () => listeners.delete(fn)
    },
  }
}

/** The one registry shared across podcast surfaces. */
export const nowPlayingHostRegistry = createNowPlayingHostRegistry()

/**
 * Hook: acquire a host token on mount, release on unmount, and re-render when the
 * election changes. Returns whether THIS host is the active (rendering) one.
 */
export function useIsActiveNowPlayingHost(): boolean {
  // Stable token captured for this component's lifetime (assigned in the effect).
  const tokenRef = useRef<symbol | null>(null)
  const [, force] = useState(0)

  useEffect(() => {
    const token = nowPlayingHostRegistry.acquire()
    tokenRef.current = token
    force((n) => n + 1)
    const unsub = nowPlayingHostRegistry.subscribe(() => force((n) => n + 1))
    return () => {
      unsub()
      nowPlayingHostRegistry.release(token)
      tokenRef.current = null
    }
  }, [])

  return tokenRef.current != null && nowPlayingHostRegistry.isActive(tokenRef.current)
}
