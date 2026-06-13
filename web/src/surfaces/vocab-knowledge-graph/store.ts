// Knowledge-graph settings store — force/display sliders ⇄ `auto_link` user config.
//
// The settings drawer sliders drive a live `ForceConfig`. When the shell is
// active we persist that config to the backend via `useApi().user.updateConfig`
// targeting the `auto_link` config group (api_models/graph.py::AutoLinkConfig,
// opaque/`[key: string]: unknown` to the web layer — so we own the field names).
// Everything works offline against the existing mock `PUT /api/user/config` route.

import { useCallback, useMemo, useRef, useState } from 'react'
import { createApiClient, type ApiClient } from '../../api'
import type { AutoLinkConfig } from '../../api'
import {
  DEFAULT_FORCES,
  FORCE_BOUNDS,
  clampForces,
  type ForceConfig,
} from './forceGraph'

const FIELD_TO_KEY: Record<keyof ForceConfig, string> = {
  centerForce: 'center_force',
  repelForce: 'repel_force',
  linkForce: 'link_force',
  linkDistance: 'link_distance',
  nodeSize: 'node_size',
  linkThickness: 'link_thickness',
}

/** Serialize a force config into the flat snake_case `auto_link` bag. */
export function forceConfigToAutoLink(f: ForceConfig): AutoLinkConfig {
  const bag: Record<string, number> = {}
  for (const field of Object.keys(FIELD_TO_KEY) as (keyof ForceConfig)[]) {
    bag[FIELD_TO_KEY[field]] = f[field]
  }
  return bag
}

function num(v: unknown, fallback: number): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : fallback
}

/** Parse an `auto_link` bag back into a clamped force config (defaults on gaps). */
export function autoLinkToForceConfig(bag: AutoLinkConfig | null | undefined): ForceConfig {
  if (!bag) return { ...DEFAULT_FORCES }
  const raw = bag as Record<string, unknown>
  const parsed: ForceConfig = {
    centerForce: num(raw[FIELD_TO_KEY.centerForce], DEFAULT_FORCES.centerForce),
    repelForce: num(raw[FIELD_TO_KEY.repelForce], DEFAULT_FORCES.repelForce),
    linkForce: num(raw[FIELD_TO_KEY.linkForce], DEFAULT_FORCES.linkForce),
    linkDistance: num(raw[FIELD_TO_KEY.linkDistance], DEFAULT_FORCES.linkDistance),
    nodeSize: num(raw[FIELD_TO_KEY.nodeSize], DEFAULT_FORCES.nodeSize),
    linkThickness: num(raw[FIELD_TO_KEY.linkThickness], DEFAULT_FORCES.linkThickness),
  }
  return clampForces(parsed)
}

/** 0..1 fill fraction of a force value within its bounds (slider track width). */
export function sliderFill(field: keyof ForceConfig, value: number): number {
  const [lo, hi] = FORCE_BOUNDS[field]
  if (hi === lo) return 0
  return Math.max(0, Math.min(1, (value - lo) / (hi - lo)))
}

/** Format a force value at the same precision as the iOS slider value label. */
export function formatForceValue(field: keyof ForceConfig, value: number): string {
  switch (field) {
    case 'centerForce':
    case 'repelForce':
    case 'linkForce':
      return value.toFixed(2) // %.2f
    case 'linkDistance':
      return value.toFixed(0) // %.0f
    case 'nodeSize':
    case 'linkThickness':
      return value.toFixed(1) // %.1f
  }
}

export interface ForceStore {
  forces: ForceConfig
  /** true while a updateConfig persist is in flight. */
  saving: boolean
  /** Live update of a single force value (also debounced-persists to auto_link). */
  setForce: (field: keyof ForceConfig, value: number) => void
  /** Reset to iOS PreviewData defaults + persist. */
  reset: () => void
  /** Whether to show isolated (unlinked) nodes — iOS "孤立節點" toggle. */
  showIsolated: boolean
  toggleIsolated: () => void
}

/**
 * Live force-config store, persisted to the `auto_link` config group. The API
 * client is created lazily from the shared factory (mock by default) — read-only
 * use of `web/src/api`, no edit to the frozen client surface. Persist failures
 * are swallowed: the graph stays usable offline even if the PUT fails.
 */
export function useForceStore(
  initial: ForceConfig = DEFAULT_FORCES,
  apiOverride?: ApiClient,
): ForceStore {
  const [forces, setForces] = useState<ForceConfig>(() => clampForces(initial))
  const [saving, setSaving] = useState(false)
  const [showIsolated, setShowIsolated] = useState(false)
  const apiRef = useRef<ApiClient | null>(apiOverride ?? null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const api = useMemo(() => {
    if (!apiRef.current) apiRef.current = createApiClient()
    return apiRef.current
  }, [])

  const persist = useCallback(
    (next: ForceConfig) => {
      if (timerRef.current) clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => {
        setSaving(true)
        void api.user
          .updateConfig({ auto_link: forceConfigToAutoLink(next) })
          .catch(() => {
            // offline / persist failure: keep local state, graph still works.
          })
          .finally(() => setSaving(false))
      }, 250)
    },
    [api],
  )

  const setForce = useCallback(
    (field: keyof ForceConfig, value: number) => {
      setForces((prev) => {
        const next = clampForces({ ...prev, [field]: value })
        persist(next)
        return next
      })
    },
    [persist],
  )

  const reset = useCallback(() => {
    const next = { ...DEFAULT_FORCES }
    setForces(next)
    persist(next)
  }, [persist])

  const toggleIsolated = useCallback(() => setShowIsolated((v) => !v), [])

  return { forces, saving, setForce, reset, showIsolated, toggleIsolated }
}
