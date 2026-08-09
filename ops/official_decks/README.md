# Official decks — git-SoT governance

Curated official flashcard decks for the Shared Decks (Explore) feature. Each
deck is a git-committed `kg.official_deck.v1` spec in this directory; the emitter
seeds it into the global `data_dir/shared_decks.db` catalog where guests browse
it. This mirrors the `ops/demo/build_demo.py` pattern: **spec is SoT → emit →
`--check` drift gate.**

Authority: `docs/plans/2026-07-09-shared-decks-library.md` §5 (governance),
§2.1 (`content_guid`), §2.3 (versioning), §3.5 (global-store backup).

## Committed specs

| spec | deckId | cards | category | scope |
|---|---|---:|---|---|
| `starter-en-zh-core.json` | `official-starter-en-zh-core` | 61 | `language` | A1–B1 everyday high-frequency (verbs / nouns / adjectives / adverbs) |
| `phrasal-verbs-essentials.json` | `official-phrasal-verbs-essentials` | 55 | `phrase` | common phrasal verbs, each noting separability |
| `exam-core-en-zh.json` | `official-exam-core-en-zh` | 56 | `exam` | academic & test-prep high-yield vocabulary |

Grown from 5-card placeholders to shippable content on 2026-08-05, ahead of the
`KGFeatureFlags.exploreEnabled` Release flip — an empty (or 10-card) catalog is
worse than no tab at all. The three decks deliberately populate three distinct
`category` values so the Explore filter chips have something to filter.

**Adding a deck:** author the JSON by hand (these are the template), `git add`
it, run `emit <spec> --json` to validate, then `check --json` to prove round-trip
fidelity over every committed spec. Keep meanings in **繁體中文** — this is
user-facing官方 content. `check` fails if you skipped the `git add`: what deploys
is the commit, not your working tree — and no CI or cutover gate will catch that
for you (see `--check` semantics below).

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

Whole-directory `check` (no spec argument) additionally asserts that **the set it
just validated equals the set git will ship**, reported as `gitIndex` in the JSON
payload:

- `untracked` — spec on disk, absent from the git index. It validated green here
  and will simply not exist in production. `git add` it.
- `missing` — spec in the git index, absent from disk (`rm` without `git rm`). It
  still ships, validated by nothing. `git rm` it or restore the file.

Either list being non-empty exits 1. If git cannot be consulted at all the gate
**errors out** rather than reporting a clean index — "I cannot see what ships"
and "what ships is fine" are the two states this exists to keep apart. `check
<single spec>` never enumerates the directory, so it reports
`gitIndex.checked: false` instead of an empty (and false) clean bill.

**This is a local, pre-commit gate — CI structurally cannot do its job, and
nothing runs it for you.** Two separate limits, worth keeping apart:

1. *CI cannot see the problem.* A CI run checks out a commit, so its index and
   working tree agree by construction: a spec you forgot to `git add` was never
   pushed and does not exist in the runner. Neither list can be non-empty there.
   Nothing in CI can know a fourth deck was intended.
2. *No automation invokes `check`.* No workflow and no ops script calls it. Its
   only automated caller is the `test_cli_check_all_committed_specs` test, and
   the local cutover gate selects that test file only when the diff touches it
   — adding `ops/official_decks/<new>.json` alone selects nothing. So **run
   `check` yourself before committing.** A green CI, and a green cutover gate,
   are both silent about whether your new deck will ship.

The frame is the **index**, not the commit: `check` proves the spec is staged,
which is the closest a pre-commit gate can get (a brand-new spec is in no commit
yet, so HEAD cannot answer). A pathspec commit (`git commit -o <other paths>`)
can still leave a staged spec out of the tree — confirm with `git show --stat
HEAD` after committing.

**Deferred (documented, not implemented in Phase 1b-ii):**

- **Pre-deploy prod-parity check (§5.3 b)** — running the emit against the live
  production catalog to detect drift between committed specs and what is actually
  seeded in prod. Deferred to the deploy runbook; the sandbox round-trip gate is
  the CI-time guard.
- **Notebook-scoped world-export projection (§5.3)** — a "single notebook" mode
  of `ops_world_export` to project one throwaway-account notebook into a
  content-only spec. **Deferred by design:** (a) it is curator *convenience*, not
  a consumer blocker — official specs are hand-authored (see the committed
  specs); (b) `world-export` emits `kg.seed_spec.v1`
  (notebooks/cards/links with review counters), a **different shape** from
  `kg.official_deck.v1`, so it is not a drop-in producer and would still need a
  seed-spec→official-deck transformer; (c) `ops_world_export` underpins the
  reproducible UI World seed with byte-equal roundtrip contracts (`ops_state_plane`
  §1.1), so touching it for a convenience path carries collateral risk
  disproportionate to the value. To bootstrap a spec today: author the JSON by
  hand (the committed examples are the template).
