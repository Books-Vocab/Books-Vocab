// Thin fetch wrapper: base-URL composition, Authorization header injection,
// JSON (de)serialization, and ApiError normalization. The actual `fetch` is
// injectable so the mock layer can swap it without monkey-patching globals and
// tests stay deterministic.

import { ApiError, normalizeErrorBody } from './errors'

export type FetchLike = (
  input: string,
  init?: RequestInit,
) => Promise<Response>

/** Resolves the bearer token at call time (so login can populate it later). */
export type TokenProvider = () => string | null | undefined

export interface TransportConfig {
  /** Base URL with no trailing slash, e.g. "https://wordnexus.lol" or "" for mock. */
  baseUrl: string
  /** Returns the current access token, or null/undefined when logged out. */
  getToken?: TokenProvider
  /** Injectable fetch (defaults to global fetch). The mock layer overrides this. */
  fetch?: FetchLike
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  /** JSON-serializable request body. */
  body?: unknown
  /** Query params; undefined/null values are dropped. */
  query?: Record<string, string | number | boolean | null | undefined>
  /** Override Authorization for this call (true=force omit even if token set). */
  anonymous?: boolean
}

export class Transport {
  private readonly baseUrl: string
  private readonly getToken: TokenProvider
  private readonly doFetch: FetchLike

  constructor(config: TransportConfig) {
    this.baseUrl = config.baseUrl.replace(/\/+$/, '')
    this.getToken = config.getToken ?? (() => null)
    this.doFetch = config.fetch ?? ((input, init) => fetch(input, init))
  }

  /** Execute a request and decode the JSON body as T. Throws ApiError on failure. */
  async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const url = this.buildUrl(path, options.query)
    const headers: Record<string, string> = { Accept: 'application/json' }

    if (!options.anonymous) {
      const token = this.getToken()
      if (token) headers.Authorization = `Bearer ${token}`
    }

    let init: RequestInit = { method: options.method ?? 'GET', headers }
    if (options.body !== undefined) {
      headers['Content-Type'] = 'application/json'
      init = { ...init, body: JSON.stringify(options.body) }
    }

    let response: Response
    try {
      response = await this.doFetch(url, init)
    } catch (cause) {
      throw new ApiError(`network error contacting ${url}`, {
        kind: 'network',
        status: 0,
      })
    }

    if (!response.ok) {
      throw await this.toHttpError(response)
    }

    if (response.status === 204) {
      return undefined as T
    }

    try {
      return (await response.json()) as T
    } catch {
      throw new ApiError(`failed to parse JSON from ${url}`, {
        kind: 'parse',
        status: response.status,
      })
    }
  }

  private buildUrl(
    path: string,
    query?: RequestOptions['query'],
  ): string {
    const base = `${this.baseUrl}${path}`
    if (!query) return base
    const params = new URLSearchParams()
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null) params.set(k, String(v))
    }
    const qs = params.toString()
    return qs ? `${base}?${qs}` : base
  }

  private async toHttpError(response: Response): Promise<ApiError> {
    let body
    try {
      const raw = await response.json()
      body = normalizeErrorBody(raw)
    } catch {
      body = undefined
    }
    const message =
      body?.detail ?? `HTTP ${response.status} ${response.statusText}`.trim()
    return new ApiError(message, {
      kind: 'http',
      status: response.status,
      code: body?.code,
      body,
    })
  }
}
