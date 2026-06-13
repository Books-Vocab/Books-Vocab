import { useSyncExternalStore } from 'react'
import { playbackEngine, type PlaybackSnapshot } from './playbackEngine'

/**
 * React view onto the singleton playback engine. Every podcast surface (home /
 * episode-list / player / mini-player) reads the SAME snapshot, so transport
 * state stays coherent as the shell mounts/unmounts surfaces around the engine.
 *
 * useSyncExternalStore keeps the snapshot tear-free across concurrent renders;
 * the engine is the external store (subscribe / getSnapshot). getSnapshot is the
 * stable server snapshot too (SSR-safe: the engine starts with a null nowPlaying).
 */
export function useSharedPlayback(): PlaybackSnapshot {
  return useSyncExternalStore(
    playbackEngine.subscribe,
    playbackEngine.getSnapshot,
    playbackEngine.getSnapshot,
  )
}
