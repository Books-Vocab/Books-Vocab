"""Audio-tag palette — single source of truth, keyed by TTS model family.

The podcast pipeline steers vocal delivery with inline `[...]` audio tags. Each
*delivery concept* (excitement, whisper, a measured pause …) renders to a
different surface tag per Gemini TTS family — and some concepts only exist on
one family. Gemini does NOT silently drop an unsupported tag; it speaks it as
literal text. So the family the script is synthesized on decides which tags are
safe.

`TAG_CONCEPTS` is the ONE table that encodes this. Everything else is derived:

    • palette(family)               → the tags an author/reviewer may use
    • sanitize_tags_for_family()    → rewrite/strip tags to a target family
    • render_palette_md(family)     → the palette block injected into prompts

Adding a new family = add one column to the relevant concepts. Adding a concept
= add one row. No palette text is duplicated anywhere — the authoring prompts
get `render_palette_md()` injected at runtime (see pipeline.py), so the old
"mirror the list in three files + a drift test" cycle is gone.

3.1 source: Gemini 3.1 official `example_audio_tags` array. 2.5 forms are the
adjective/gerund set Gemini 2.5 TTS reliably honors (the pipeline's original
pre-3.1 palette); concepts with no 2.5 column are stripped when synthesizing on
2.5 rather than voiced as literal words.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TagConcept:
    """One delivery intent and its surface tag per family.

    ``forms`` maps family id ("3.1", "2.5", …) → the lowercase text inside the
    brackets. A family absent from ``forms`` has no supported tag for this
    concept, so on that family the tag is stripped (never spoken).
    """

    id: str
    kind: str  # "emotion" | "energy" | "pacing_nonverbal" | "pause"
    forms: dict[str, str]


# ─────────────────────────── the table ───────────────────────────
# Emotion concepts carry a 2.5 adjective form only where Gemini 2.5 honors one;
# the rest are 3.1-only (richer prosody, no reliable 2.5 surface form).
TAG_CONCEPTS: tuple[TagConcept, ...] = (
    # — emotion: 3.1 noun ⇄ 2.5 adjective —
    TagConcept("excitement", "emotion", {"3.1": "excitement", "2.5": "excited"}),
    TagConcept("skepticism", "emotion", {"3.1": "skepticism", "2.5": "skeptical"}),
    TagConcept("amusement", "emotion", {"3.1": "amusement", "2.5": "amused"}),
    TagConcept("uncertainty", "emotion", {"3.1": "uncertainty", "2.5": "uncertain"}),
    TagConcept("sadness", "emotion", {"3.1": "sadness", "2.5": "sad"}),
    TagConcept("surprise", "emotion", {"3.1": "surprise", "2.5": "surprised"}),
    TagConcept("happiness", "emotion", {"3.1": "happiness", "2.5": "happy"}),
    TagConcept("sarcasm", "emotion", {"3.1": "sarcasm", "2.5": "sarcastic"}),
    TagConcept("sympathy", "emotion", {"3.1": "sympathy", "2.5": "empathetic"}),
    # — emotion: 3.1-only —
    TagConcept("curiosity", "emotion", {"3.1": "curiosity"}),
    TagConcept("interest", "emotion", {"3.1": "interest"}),
    TagConcept("enthusiasm", "emotion", {"3.1": "enthusiasm"}),
    TagConcept("humor", "emotion", {"3.1": "humor"}),
    TagConcept("joy", "emotion", {"3.1": "joy"}),
    TagConcept("awe", "emotion", {"3.1": "awe"}),
    TagConcept("admiration", "emotion", {"3.1": "admiration"}),
    TagConcept("shock", "emotion", {"3.1": "shock"}),
    TagConcept("doubt", "emotion", {"3.1": "doubt"}),
    TagConcept("confusion", "emotion", {"3.1": "confusion"}),
    TagConcept("determination", "emotion", {"3.1": "determination"}),
    TagConcept("confidence", "emotion", {"3.1": "confidence"}),
    TagConcept("caring", "emotion", {"3.1": "caring"}),
    TagConcept("melancholy", "emotion", {"3.1": "melancholy"}),
    TagConcept("nostalgia", "emotion", {"3.1": "nostalgia"}),
    TagConcept("grief", "emotion", {"3.1": "grief"}),
    TagConcept("relief", "emotion", {"3.1": "relief"}),
    TagConcept("satisfaction", "emotion", {"3.1": "satisfaction"}),
    TagConcept("frustration", "emotion", {"3.1": "frustration"}),
    TagConcept("disappointment", "emotion", {"3.1": "disappointment"}),
    TagConcept("tension", "emotion", {"3.1": "tension"}),
    TagConcept("anticipation", "emotion", {"3.1": "anticipation"}),
    TagConcept("hope", "emotion", {"3.1": "hope"}),
    TagConcept("passion", "emotion", {"3.1": "passion"}),
    TagConcept("yearning", "emotion", {"3.1": "yearning"}),
    # — energy: 3.1-only (paragraph-level dynamics) —
    TagConcept("high_energy", "energy", {"3.1": "high energy"}),
    TagConcept("low_energy", "energy", {"3.1": "low energy"}),
    # — pacing / non-verbal: 3.1 base ⇄ 2.5 gerund —
    TagConcept("whisper", "pacing_nonverbal", {"3.1": "whispers", "2.5": "whispering"}),
    TagConcept("sigh", "pacing_nonverbal", {"3.1": "sighs", "2.5": "sighing"}),
    TagConcept("laugh", "pacing_nonverbal", {"3.1": "laughs", "2.5": "laughing"}),
    TagConcept("giggle", "pacing_nonverbal", {"3.1": "giggles", "2.5": "chuckling"}),
    TagConcept("slow", "pacing_nonverbal", {"3.1": "slow", "2.5": "speaking slowly"}),
    TagConcept("fast", "pacing_nonverbal", {"3.1": "fast", "2.5": "speaking quickly"}),
    # — non-verbal: 3.1-only —
    TagConcept("gasp", "pacing_nonverbal", {"3.1": "gasp"}),
    # — pauses: 3.1-only (Mode 4 measured silence; REPLACE SSML <break>) —
    TagConcept("short_pause", "pause", {"3.1": "short pause"}),
    TagConcept("medium_pause", "pause", {"3.1": "medium pause"}),
    TagConcept("long_pause", "pause", {"3.1": "long pause"}),
)

# Human-facing engine name per family (used in injected prompt prose).
ENGINE_NAMES: dict[str, str] = {
    "3.1": "Gemini 3.1 Flash TTS",
    "2.5": "Gemini 2.5 TTS",
}

# Families the registry can author/sanitize for.
KNOWN_FAMILIES: frozenset[str] = frozenset(
    f for c in TAG_CONCEPTS for f in c.forms
)

# Surface form (any family) → owning concept. Asserted collision-free below.
_FORM_TO_CONCEPT: dict[str, TagConcept] = {}
for _c in TAG_CONCEPTS:
    for _form in _c.forms.values():
        if _form in _FORM_TO_CONCEPT and _FORM_TO_CONCEPT[_form].id != _c.id:
            raise AssertionError(
                f"audio-tag form {_form!r} claimed by two concepts: "
                f"{_FORM_TO_CONCEPT[_form].id} and {_c.id}"
            )
        _FORM_TO_CONCEPT[_form] = _c

# Bracket-tag matcher (single level — content placeholders never nest tags).
_TAG_RE = re.compile(r"\[([^\[\]]+)\]")


def palette(family: str) -> set[str]:
    """The set of inline tags valid for ``family`` (the authoring whitelist)."""
    return {c.forms[family] for c in TAG_CONCEPTS if family in c.forms}


def engine_name(family: str) -> str:
    return ENGINE_NAMES.get(family, f"Gemini {family} TTS")


def sanitize_tags_for_family(text: str, family: str) -> tuple[str, dict[str, int]]:
    """Rewrite/strip audio tags so they are safe to synthesize on ``family``.

    For every ``[tag]``:
      • not a known palette form anywhere  → kept (it is spoken CONTENT, e.g. a
        habit-stacking placeholder ``[NEW HABIT]``)
      • concept HAS a form on ``family``   → rewritten to that form (a no-op when
        it is already the right form; upgrades a 2.5 form to its 3.1 noun, or
        downgrades a 3.1 noun to its 2.5 adjective)
      • concept has NO form on ``family``  → stripped (would otherwise be voiced)

    Unknown ``family`` (no registry) → text returned verbatim: we cannot know
    what is safe, so we leave it rather than strip everything. Prompt injection
    fails loudly on an unknown family instead (see pipeline.py).

    Returns the cleaned text and a ``{change_key: count}`` map for logging.
    """
    if family not in KNOWN_FAMILIES:
        return text, {}

    changes: dict[str, int] = {}

    def _bump(key: str) -> None:
        changes[key] = changes.get(key, 0) + 1

    def _repl(m: re.Match) -> str:
        key = m.group(1).strip().lower()
        concept = _FORM_TO_CONCEPT.get(key)
        if concept is None:
            return m.group(0)  # non-palette bracket = spoken content, keep
        target = concept.forms.get(family)
        if target is None:
            _bump(f"{key}(strip)")  # 3.1-only tag on a family without it
            return ""
        if target == key:
            return m.group(0)  # already the right form
        _bump(f"{key}->{target}")
        return f"[{target}]"

    out = _TAG_RE.sub(_repl, text)
    if changes:
        # Tidy whitespace left by stripped tags: collapse interior space runs,
        # drop space-before-punct, strip line-leading/trailing space. Never
        # touches newlines (parse_script is line-based).
        out = re.sub(r"[ \t]{2,}", " ", out)
        out = re.sub(r" +([,.!?;:])", r"\1", out)
        out = re.sub(r"(?m)^[ \t]+", "", out)
        out = re.sub(r"(?m)[ \t]+$", "", out)
    return out, changes


def render_palette_md(family: str) -> str:
    """Render the palette block injected into the authoring/review prompts.

    Self-describing per family: groups with no tags on this family are omitted
    and called out, so e.g. the 2.5 block tells the author it has no energy/pause
    tags (use prose/pacing instead) rather than silently leaving them available.
    """
    groups: list[tuple[str, str]] = [
        ("emotion", "Emotion"),
        ("energy", "Energy (paragraph-level dynamics)"),
        ("pacing_nonverbal", "Pacing & non-verbal"),
        ("pause", "Pauses (measured silence — these are tags, NOT SSML)"),
    ]
    lines = [
        f"Audio-tag palette for **{engine_name(family)}** (family `{family}`). "
        f"Use ONLY these inline tags — the reviewer rejects anything outside this set."
    ]
    present_kinds: set[str] = set()
    for kind, heading in groups:
        tags = sorted(c.forms[family] for c in TAG_CONCEPTS if c.kind == kind and family in c.forms)
        if not tags:
            continue
        present_kinds.add(kind)
        rendered = ", ".join(f"`[{t}]`" for t in tags)
        lines.append(f"- **{heading}**: {rendered}")
    if "energy" not in present_kinds:
        lines.append("- _No energy tags on this family — shape dynamics through prose and pacing._")
    if "pause" not in present_kinds:
        lines.append("- _No pause tags on this family — let em-dashes / ellipses carry beats._")
    return "\n".join(lines)


# ─────────────────────── backward-compat exports ───────────────────────
# Consumers that predate the registry. Derived, never hand-maintained.
# CANONICAL = the 3.1 palette; LEGACY_TO_CANONICAL = 2.5 form → 3.1 form.
CANONICAL: frozenset[str] = frozenset(palette("3.1"))
LEGACY_TO_CANONICAL: dict[str, str] = {
    c.forms["2.5"]: c.forms["3.1"]
    for c in TAG_CONCEPTS
    if "2.5" in c.forms and "3.1" in c.forms
}
