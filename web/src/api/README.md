# web/src/api — typed data layer

Typed API client + in-process mock backend. Bridges web surfaces from fixtures
toward real data. **No surface wires into this yet** — this slice ships the
client, mock, and tests only.

## Layout

| file | role |
|------|------|
| `types.ts` | Hand-written TS mirrors of backend pydantic schemas (`backend/src/kg/api_models/*.py`). **SoT = backend.** Copy field names verbatim; never invent. |
| `errors.ts` | `ApiError` (normalized) + FastAPI `detail` body normalization. |
| `transport.ts` | Thin `fetch` wrapper: base URL, `Authorization`, JSON, error normalization. `fetch` is injectable. |
| `clients.ts` | Domain clients (`auth` / `vocabulary` / `todayReview` / `podcast` / `user`), one method per backend route. |
| `mock/data.ts` | Mock payloads, API-shaped, derived from surface fixtures. |
| `mock/handler.ts` | `createMockFetch()` — a `FetchLike` matching the real paths. Zero deps (no msw). |
| `index.ts` | `createApiClient()` factory + public re-exports. |

## Usage (for surface authors)

```ts
import { createApiClient, ApiError } from '../api'

// Default mode = mock (VITE_API_MODE). Pass getToken to send a Bearer header.
const api = createApiClient({ getToken: () => sessionToken })

try {
  const cards = await api.vocabulary.list()
  const queue = await api.todayReview.queue()
  const series = await api.podcast.series()        // guest-allowed
  const cfg = await api.user.config()
} catch (e) {
  if (e instanceof ApiError && e.isUnauthorized) {
    // 401 → token missing/invalid → route to login
  }
}
```

Every method returns the typed response from `types.ts`. Errors are always
`ApiError` (`status`, `code`, `kind`, `isUnauthorized`, `isForbidden`).

## Modes

Set via env (`web/.env`, read in `index.ts`):

- `VITE_API_MODE=mock` (**default**) — in-process mock backend, full
  functionality, zero network. Mock enforces auth: protected routes reply
  `401 {code:auth_required}` without a Bearer header (browse podcast +
  `/auth/verify` are anonymous), so the 401 path is exercisable.
- `VITE_API_MODE=real` — points transport at `VITE_API_BASE_URL`. **Live
  wiring (CORS, real base URL) is intentionally NOT done in this slice** —
  needs explicit sign-off (production CORS change). Switching modes only swaps
  the fetch transport + base URL; the client surface is identical.

## Covered endpoints

| domain | method · path | backend router |
|--------|---------------|----------------|
| auth | `POST /auth/verify` | `auth.py` |
| vocabulary | `GET /api/vocab` · `GET /api/vocab/{word}` · `POST /api/vocab` | `vocab.py` |
| today review | `GET /api/vocab` (queue) · `PATCH /api/vocab/review` · `GET\|PATCH /api/vocab/review-events` | `vocab.py` |
| podcast | `GET /api/podcasts` · `GET /api/podcasts/{sid}` · `GET\|POST /api/podcasts/.../progress` | `podcast_browse.py` · `podcast_progress.py` |
| user | `GET\|PUT /api/user/config` · `GET /api/user/entitlements` · `GET /api/user/quota` | `user.py` · `billing.py` |

**Not covered** (out of scope for this slice): web OAuth redirect flow
(`web_auth.py`), notebooks, translate, pipeline, graph-link mutations, billing
receipts, podcast media/subtitle bytes (binary, tier-gated). There is **no**
username/password login and **no** token-refresh endpoint — `POST /auth/verify`
exchanges a provider OAuth token; re-verify to renew.

## Keeping in sync

When a backend pydantic schema or route changes, update `types.ts` /
`clients.ts` in the same PR (mirrors the iOS↔backend discipline). The hand-typed
interfaces are the only drift surface — each carries a `// api_models/...` ref.
