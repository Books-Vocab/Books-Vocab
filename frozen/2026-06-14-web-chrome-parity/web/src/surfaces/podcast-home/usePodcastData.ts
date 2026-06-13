import { useEffect, useRef, useState } from 'react'
import { createApiClient, type ApiClient } from '../../api'
import type {
  EntitlementsResponse,
  PodcastProgressListResponse,
  PodcastSeriesSummary,
} from '../../api/types'

/**
 * Live data for the shell-gated functional podcast flow. Mock-first: with
 * VITE_API_MODE unset (default 'mock') createApiClient() serves the in-process
 * mock backend, so this works fully offline.
 *
 * Browse (GET /api/podcasts) is anonymous; progress + entitlements require a
 * Bearer token. The offline "devLogin" equivalent is POST /auth/verify, which
 * the mock mints into a deterministic token — we hold it in a closure token
 * provider so the transport attaches it to the authed calls. Tier therefore
 * resolves to 'free' (logged in, no active pro) under the default mock, which
 * exercises the preview-banner + Pro-lock gating paths.
 */

export interface PodcastData {
  loading: boolean
  /** non-null only when login/fetch threw — UI degrades to guest tier. */
  error: string | null
  series: PodcastSeriesSummary[]
  progress: PodcastProgressListResponse
  entitlements: EntitlementsResponse | null
  /** true once /auth/verify minted a token (drives free-vs-guest tier). */
  hasToken: boolean
  /** live client for detail fetches + progress writes (stable per mount). */
  api: ApiClient
}

const EMPTY_PROGRESS: PodcastProgressListResponse = { items: [] }

export function usePodcastData(): PodcastData {
  // Token lives in a ref the transport re-reads per request (getToken). The
  // effect populates it after /auth/verify; the same client instance then
  // attaches it to the authed calls.
  const tokenRef = useRef<string | null>(null)
  const [api] = useState<ApiClient>(() => createApiClient({ getToken: () => tokenRef.current }))

  const [state, setState] = useState<{
    loading: boolean
    error: string | null
    series: PodcastSeriesSummary[]
    progress: PodcastProgressListResponse
    entitlements: EntitlementsResponse | null
    hasToken: boolean
  }>({
    loading: true,
    error: null,
    series: [],
    progress: EMPTY_PROGRESS,
    entitlements: null,
    hasToken: false,
  })

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        // Anonymous browse first — always available.
        const series = await api.podcast.series()
        // Offline devLogin: mint a mock token so authed calls succeed.
        let hasToken = false
        let progress = EMPTY_PROGRESS
        let entitlements: EntitlementsResponse | null = null
        try {
          const auth = await api.auth.verify({ provider: 'apple', token: 'mock-provider-token' })
          tokenRef.current = auth.access_token
          hasToken = true
          ;[progress, entitlements] = await Promise.all([
            api.podcast.progress(),
            api.user.entitlements(),
          ])
        } catch {
          // Stay a guest: browse-only. Not fatal.
          hasToken = false
        }
        if (cancelled) return
        setState({ loading: false, error: null, series, progress, entitlements, hasToken })
      } catch (e) {
        if (cancelled) return
        setState((s) => ({
          ...s,
          loading: false,
          error: e instanceof Error ? e.message : 'failed to load podcasts',
        }))
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [api])

  return { ...state, api }
}
