<!-- doc-meta
tier: reference
authority: SoT
update_trigger: code-change
scope:
  - ops/backlog_store.py
  - ops/backlog.py
  - ops/lib/worktree_orchestrator_claims.py
  - ops/lib/worktree_orchestrator_core_gate_inputs.py
verified_against: 1885669bc7dbba578f6e30792025225969a352bb
-->
# Backlog store control plane

Backlog tickets are data-plane records, not source-code changes. The code
checkout and the ticket store therefore have separate freshness and landing
semantics.

## Store selection

`ops/backlog.py` accepts `--store` on commands that read or write tickets. When
that flag is omitted, `KG_BACKLOG_STORE` selects the configured store. A
relative environment value is resolved from the repository root; an absolute
value may point outside the code checkout.

For compatibility, an unset `KG_BACKLOG_STORE` continues to use
`docs/runbook/backlog/`. This is a compatibility mode, not the independent
deployment mode. The independent mode must be explicitly activated and its
existing entries migrated and verified before dispatch is enabled.

An external store is described as `kg.backlog.store.v1` and is identified by
its resolved path. Its human-readable `improvement_backlog.md` view is written
beside the external store, never into the code checkout by default.

## Git and Gate boundary

Adding, grooming, verifying, or updating a ticket in an external store does
not advance the code repository's `main`, does not make a feature branch stale,
and does not require a code cutover. A ticket-data write may still require the
small `backlog-validate` check when the workflow asks for it; it must not be
treated as a source diff or as a reason to rerun unrelated code gates.

The gate input contract labels an external backlog as `external-store` and
marks it non-reusable until the store content has an explicit, independent
fingerprint contract. This is fail-closed: a changed ticket cannot silently
reuse a verdict computed from a different ticket store snapshot.

## Worktree admission

Ordinary claim, dispatch, and campaign ticket selection use the same configured
store resolver as the backlog CLI. Scratch repositories used by tests retain a
repo-local legacy store so a fixture cannot read or mutate an operator's real
external ledger.

Campaign reservation commit is lifecycle-owned by Manager. Until that command
is routed through the same resolver and its manifest is revalidated, an
external store must not be used to dispatch a campaign. A reservation created
against the legacy store is not evidence for an external-store campaign.

## Activation checklist

1. Choose a durable external path and set `KG_BACKLOG_STORE` for every process
   that reads or writes the ledger.
2. Copy the existing JSON entries and validate the external store before
   changing the default operator environment.
3. Confirm the campaign-reservation command, manifest digest, and child claim
   all resolve the same store.
4. Only then enable dispatch; keep code `main` and the backlog store's own
   versioning/backup lifecycle separate.
