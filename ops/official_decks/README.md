# Official decks — git-SoT governance

Curated official flashcard decks for the Shared Decks (Explore) feature. Each
deck is a git-committed `kg.official_deck.v1` spec in this directory; the emitter
seeds it into the global `data_dir/shared_decks.db` catalog where guests browse
it. This mirrors the `ops/demo/build_demo.py` pattern: **spec is SoT → emit →
`--check` drift gate.**

Authority: `docs/plans/2026-07-09-shared-decks-library.md` §5 (governance),
§2.1 (`content_guid`), §2.3 (versioning), §3.5 (global-store backup).

## Emitter

Run via uv from the backend venv (needs the `kg` package on path):

```bash
# validate + plan only (zero disk writes)
(cd backend && uv run python ../ops/official_decks/build_official.py emit \
    ../ops/official_decks/starter-en-zh-core.json --json)

# round-trip self-consistency gate over ALL committed specs (PR gate; exit 1 on drift)
(cd backend && uv run python ../ops/official_decks/build_official.py check --json)

# land into shared_decks.db (dry-run default → --commit; approval-gated, U6)
(cd backend && KG_DATA_DIR=/path/to/data uv run python \
    ../ops/official_decks/build_official.py emit \
    ../ops/official_decks/starter-en-zh-core.json --commit --json)
```

`--commit` snapshots the whole data-dir (`backup_world`, label
`shared-decks-official`) **before** writing. It writes only to the resolved
`KG_DATA_DIR` and never auto-deploys — production injection requires an explicit
go (U6 precedent). Prefer the production wrapper `./ops/devops_kg_safe.sh` for
prod data.

## Spec format (`kg.official_deck.v1`)

| field | required | notes |
|---|---|---|
| `schema` | yes | must be `"kg.official_deck.v1"` |
| `deckId` | yes | stable id, `^[A-Za-z0-9_-]{1,64}$`; re-emit targets the same deck row (idempotent upsert) |
| `title` | yes | non-empty |
| `description` | no | |
| `category` | no | coarse filter enum: `language` \| `exam` \| `phrase` \| `custom` |
| `languagePair` | no | e.g. `en-zh` (curator-supplied; Card/Notebook have no such field) |
| `tags` | no | list of strings |
| `color` / `coverPattern` | no | procedural cover; no image in v1 |
| `cards[]` | yes | non-empty; each card is the **content plane only** |

Each card: `content` (req) · `pos` · `meaning` (req) · `examples[]` ·
`collocations[]` · `note` · `difficulty` · `mode` (default `recognition`) ·
`rootForm` · `inflections[]`. **No SRS fields** — a shared card physically
cannot carry review schedule (the `shared_deck_card` table has zero SRS columns).

### Server-authoritative fields (never in a spec)

`source` / `ownerId` / `visibility` / `status` are stamped by
`SharedDeckStore.publish_official` (always `official` / `NULL` / `official` /
`active`). The method has no such parameters, so a spec **cannot** forge a
verified badge even if it smuggles `source: "community"`. This invariant is the
load-bearing badge-trust property and has a dedicated negative test.

### Identity, hashing, versioning

- `content_guid = uuid5(NS, content_nfc_lower | pos | mode | meaning_nfc_lower)`
  — covers pos+mode+meaning so homographs (`lead` metal vs verb) never collide.
  Homograph-identical cards in one spec are deduped (first wins).
- `content_hash` = SHA-256 over the content plane, deterministic order, excludes
  timestamps. Re-emitting identical content is a **no-op** (no version bump);
  changing content mints a **new version**, flips `current_version` atomically,
  and leaves the prior version's cards immutable.

## `--check` semantics (what the gate covers, and what it defers)

`check` runs **round-trip self-consistency** in a throwaway sandbox: emit each
spec → project the stored rows back → assert the projection equals the
spec-as-written. It catches malformed specs, colliding/duplicate cards (which
collapse under the guid UNIQUE), and any projection-fidelity regression. This is
the sandbox PR gate (§5.3 a).

**Deferred (documented, not implemented in Phase 1b-ii):**

- **Pre-deploy prod-parity check (§5.3 b)** — running the emit against the live
  production catalog to detect drift between committed specs and what is actually
  seeded in prod. Deferred to the deploy runbook; the sandbox round-trip gate is
  the CI-time guard.
- **Notebook-scoped world-export projection (§5.3)** — a "single notebook" mode
  of `ops_world_export` to project one throwaway-account notebook into a
  content-only spec. **Deferred by design:** (a) it is curator *convenience*, not
  a consumer blocker — Phase 1 official specs are hand-authored (see the two
  committed examples); (b) `world-export` emits `kg.seed_spec.v1`
  (notebooks/cards/links with review counters), a **different shape** from
  `kg.official_deck.v1`, so it is not a drop-in producer and would still need a
  seed-spec→official-deck transformer; (c) `ops_world_export` underpins the
  marketing-account SoT with byte-equal roundtrip contracts (`ops_state_plane`
  §1.1), so touching it for a convenience path carries collateral risk
  disproportionate to the value. To bootstrap a spec today: author the JSON by
  hand (the committed examples are the template).
