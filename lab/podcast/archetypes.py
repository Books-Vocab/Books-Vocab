"""Archetype registry — single source of truth for podcast production modes.

The pipeline produces different *kinds* of show from different *kinds* of book.
A non-fiction idea book wants an explainer with external enrichment; a novel
wants a spoiler-aware narrative companion; a multi-book saga wants cross-book
continuity. Rather than branch the 13-stage pipeline per kind, each archetype
selects a *prompt set* (via filename suffix) and a few behavioral flags. Adding
an archetype = appending one entry here + dropping `<stage>_<suffix>.md` prompt
variants; the resolver falls through to the base prompt for any stage a variant
doesn't override, so an archetype only forks the stages it actually needs.

This module is imported by both `triage.py` (classifies a book → archetype) and
`pipeline.py` (drives prompt resolution + tool grants from the chosen archetype).

Design invariants (see ARCHETYPE_PLAN.md):
- `STAGES` stays frozen at 13 — archetypes never add stages.
- The default `nonfiction` archetype has `suffix=None`, so EVERY prompt resolves
  to the base file → provably zero behavior change for existing non-fiction runs.
- `archetype` × `spoiler_mode` are orthogonal: fiction is ONE prompt set, the
  spoiler mode is a parameter, not a duplicated prompt set.
"""

from __future__ import annotations

from typing import TypedDict


class Archetype(TypedDict):
    label: str  # human-facing show kind, shown by triage
    suffix: str | None  # prompt-variant filename suffix; None → always base prompt
    requires_spoiler_policy: bool  # if True, --spoiler-mode is mandatory
    spoiler_modes: list[str]  # allowed --spoiler-mode values ([] if N/A)
    enricher: str  # "web" → external evidence; "canon" → inward/canon-focused


ARCHETYPES: dict[str, Archetype] = {
    "nonfiction": {
        # Fallback archetype. No `_nonfiction.md` variants exist, so the resolver
        # always falls through to the base prompt — current behavior, zero change.
        "label": "Idea Explainer",
        "suffix": None,
        "requires_spoiler_policy": False,
        "spoiler_modes": [],
        "enricher": "web",
    },
    "fiction": {
        # Narrative umbrella. spoiler_mode decides the show's shape:
        #   readalong     — chapter-by-chapter, strict reading-order, no peeking
        #   retrospective — assumes the listener finished; free cross-references
        "label": "Narrative / Read-Along",
        "suffix": "fiction",
        "requires_spoiler_policy": True,
        "spoiler_modes": ["readalong", "retrospective"],
        "enricher": "canon",
    },
    "saga": {
        # Multi-book series (a trilogy / a complete set) rendered as ONE
        # continuous feed with cross-book continuity. Reuses the fiction prompt
        # set (suffix "fiction") plus saga-only overlays; the multi-book layout
        # (series grouping, series bible, cross-book spoiler horizon) is driven
        # by saga-specific wiring in the pipeline, not by a separate prompt set.
        "label": "Saga Companion",
        "suffix": "fiction",
        "requires_spoiler_policy": True,
        "spoiler_modes": ["readalong", "retrospective"],
        "enricher": "canon",
    },
}

DEFAULT_ARCHETYPE = "nonfiction"

# Archetypes that span multiple source books and need series-layout handling
# (grouped workspace, series bible, cross-book reading-order spoiler horizon).
MULTI_BOOK_ARCHETYPES: frozenset[str] = frozenset({"saga"})


def get(archetype: str) -> Archetype:
    """Return the registry entry, defaulting to nonfiction for unknown keys."""
    return ARCHETYPES.get(archetype, ARCHETYPES[DEFAULT_ARCHETYPE])


def validate_spoiler_mode(archetype: str, spoiler_mode: str | None) -> str | None:
    """Validate a (archetype, spoiler_mode) pair. Returns an error string if the
    combination is invalid, else None.

    - If the archetype requires a spoiler policy, spoiler_mode is mandatory and
      must be one of its allowed modes.
    - If it does NOT, spoiler_mode must be absent (passing one is a usage error).
    """
    entry = get(archetype)
    if entry["requires_spoiler_policy"]:
        if spoiler_mode is None:
            return f"archetype '{archetype}' requires --spoiler-mode (one of {entry['spoiler_modes']})"
        if spoiler_mode not in entry["spoiler_modes"]:
            return (
                f"--spoiler-mode '{spoiler_mode}' invalid for archetype '{archetype}'; "
                f"choose one of {entry['spoiler_modes']}"
            )
    elif spoiler_mode is not None:
        return f"archetype '{archetype}' does not take --spoiler-mode"
    return None
