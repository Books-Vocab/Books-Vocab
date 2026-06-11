// Normalized API error. Every transport failure (HTTP non-2xx, network error,
// or malformed JSON) is surfaced as an ApiError so callers branch on `status`
// and `code` instead of reverse-engineering fetch Response objects.

export type ApiErrorKind = 'http' | 'network' | 'parse'

export interface ApiErrorBody {
  /** Machine code from backend `{ "detail": { "code": ... } }` or `{ "code": ... }`. */
  code?: string
  /** Human-readable message (backend `detail` string, or our fallback). */
  detail?: string
  [key: string]: unknown
}

export class ApiError extends Error {
  readonly kind: ApiErrorKind
  /** HTTP status (0 for network/parse failures). */
  readonly status: number
  /** Backend machine code when present (e.g. "auth_required", "upgrade_required"). */
  readonly code?: string
  /** Raw parsed error body, when the response carried JSON. */
  readonly body?: ApiErrorBody

  constructor(
    message: string,
    opts: { kind: ApiErrorKind; status: number; code?: string; body?: ApiErrorBody },
  ) {
    super(message)
    this.name = 'ApiError'
    this.kind = opts.kind
    this.status = opts.status
    this.code = opts.code
    this.body = opts.body
  }

  /** True for 401 — unauthenticated / token invalid. */
  get isUnauthorized(): boolean {
    return this.status === 401
  }

  /** True for 403 — authenticated but not entitled (e.g. upgrade_required). */
  get isForbidden(): boolean {
    return this.status === 403
  }
}

/**
 * FastAPI conventionally returns errors as `{ "detail": ... }` where `detail`
 * is either a string or an object (our gated endpoints use
 * `{ "detail": { "code": ..., ... } }`). Normalize both into ApiErrorBody.
 */
export function normalizeErrorBody(raw: unknown): ApiErrorBody {
  if (raw && typeof raw === 'object') {
    const obj = raw as Record<string, unknown>
    const detail = obj.detail
    if (detail && typeof detail === 'object') {
      // FastAPI HTTPException(detail={code, ...})
      const d = detail as Record<string, unknown>
      return {
        ...d,
        code: typeof d.code === 'string' ? d.code : undefined,
        detail: typeof d.message === 'string' ? d.message : undefined,
      }
    }
    if (typeof detail === 'string') {
      return { detail }
    }
    // Already a flat { code, detail } shape (our mock layer emits this).
    return {
      ...obj,
      code: typeof obj.code === 'string' ? obj.code : undefined,
      detail: typeof obj.detail === 'string' ? obj.detail : undefined,
    }
  }
  return {}
}
