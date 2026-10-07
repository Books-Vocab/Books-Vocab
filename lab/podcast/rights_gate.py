#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Copyright line for the podcast pipeline (#2094): rights sidecar + verbatim gate.

Project stance: transformative commentary is fine; the HARD line is that a book
which is not public domain never becomes full_text / audiobook-like verbatim
audio. This module is the single code owner of that line and is deliberately
stdlib-only so ``pipeline.py``, ``monitor/server.py`` and the one-off workspace
report all share one implementation.

* **Rights sidecar** ``<ws>/.rights`` holds ``public_domain | licensed |
  copyrighted``. It is written once at workspace creation; a missing sidecar
  means ``copyrighted`` (fail closed) and a resume can never change it.
* **Prompt policy** ``{rights_policy}`` / ``{strategy_options}`` placeholders:
  only a public-domain book is ever offered the ``full_text`` strategy.
* **Plan validator** flags any episode plan whose ``Strategy`` is full text.
* **Verbatim gate** measures each script / subtitle against
  ``source/chapters``: the longest near-verbatim run and the share of words that
  sit inside copied runs. Thresholds come from the workflow's
  ``qa_thresholds.verbatim`` (defaults below are the conservative fallback).

Report over existing workspaces (read-only, writes nothing into them):

    uv run rights_gate.py report workspaces/ --json out.json --md out.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

RIGHTS_SIDECAR = ".rights"
PUBLIC_DOMAIN = "public_domain"
LICENSED = "licensed"
COPYRIGHTED = "copyrighted"
RIGHTS_VALUES = (PUBLIC_DOMAIN, LICENSED, COPYRIGHTED)
DEFAULT_RIGHTS = COPYRIGHTED
REPORT_FILE = "verbatim_qa.json"
VALIDATOR_VERSION = "v1"

_COMMENTARY_STRATEGIES = ("key_passages", "summary_plus_quotes")
_PD_STRATEGIES = ("full_text",) + _COMMENTARY_STRATEGIES


class RightsError(ValueError):
    """A rights sidecar is unreadable or a run tried to change frozen rights."""


# ─── Rights sidecar ─────────────────────────────────────────────────────────


def read_rights(workspace: Path) -> str:
    """Return the workspace rights. Missing sidecar → ``copyrighted``.

    An unknown value raises: a corrupt sidecar must never be guessed into a
    weaker class.
    """
    try:
        value = (workspace / RIGHTS_SIDECAR).read_text().strip()
    except FileNotFoundError:
        return DEFAULT_RIGHTS
    except (OSError, UnicodeDecodeError) as exc:
        raise RightsError(f"cannot read {workspace / RIGHTS_SIDECAR}: {exc}") from exc
    if value not in RIGHTS_VALUES:
        raise RightsError(
            f"{workspace / RIGHTS_SIDECAR} contains {value!r}; expected one of "
            f"{', '.join(RIGHTS_VALUES)}"
        )
    return value


def resolve_workspace_rights(
    workspace: Path, requested: str | None, *, created: bool
) -> str:
    """Freeze rights at creation; refuse any change on resume.

    ``created`` is True only when this invocation created the workspace. A
    pre-existing workspace without a sidecar predates the rights field and is
    pinned to ``copyrighted`` (fail closed); relabelling it is a deliberate
    manual act on the sidecar file, never a resume flag.
    """
    if requested is not None and requested not in RIGHTS_VALUES:
        raise RightsError(
            f"unknown rights {requested!r}; expected one of {', '.join(RIGHTS_VALUES)}"
        )
    sidecar = workspace / RIGHTS_SIDECAR
    if sidecar.is_file():
        frozen = read_rights(workspace)
        if requested and requested != frozen:
            raise RightsError(
                f"workspace rights are frozen at creation as {frozen!r}; cannot "
                f"resume as --rights {requested}. Omit --rights to use the saved one."
            )
        return frozen
    if created:
        value = requested or DEFAULT_RIGHTS
        sidecar.write_text(value + "\n")
        return value
    if requested and requested != DEFAULT_RIGHTS:
        raise RightsError(
            f"legacy workspace has no {RIGHTS_SIDECAR} sidecar, so it is treated as "
            f"{DEFAULT_RIGHTS!r} (fail closed); rights cannot be changed on resume. "
            f"If you have verified the book is {requested}, write it by hand: "
            f"echo {requested} > {sidecar}"
        )
    sidecar.write_text(DEFAULT_RIGHTS + "\n")
    return DEFAULT_RIGHTS


# ─── Thresholds ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class VerbatimThresholds:
    """Conservative defaults; ``workflow.json`` ``qa_thresholds.verbatim`` wins.

    * ``min_run_words`` — a near-verbatim run shorter than this is not counted
      as copied (stops idioms and chance phrases from counting);
    * ``max_run_words`` — longest single near-verbatim run allowed per text;
    * ``max_copied_share`` — max fraction of a text's words inside counted runs;
    * ``gap_words`` — a run tolerates this many inserted/merged words (OCR word
      merges, an interjection, a host hand-off) and still counts as one run.
    """

    min_run_words: int = 12
    max_run_words: int = 30
    max_copied_share: float = 0.03
    gap_words: int = 2

    def __post_init__(self) -> None:
        for name in ("min_run_words", "max_run_words", "gap_words"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"verbatim {name} must be an integer, got {value!r}")
        if self.min_run_words < 1 or self.max_run_words < 1:
            raise ValueError("verbatim run thresholds must be >= 1")
        if self.min_run_words > self.max_run_words:
            raise ValueError("verbatim min_run_words must be <= max_run_words")
        if not 0 <= self.gap_words <= 10:
            raise ValueError("verbatim gap_words must be within 0..10")
        share = self.max_copied_share
        if isinstance(share, bool) or not isinstance(share, (int, float)):
            raise ValueError(
                f"verbatim max_copied_share must be a number, got {share!r}"
            )
        if not 0 <= share <= 1:
            raise ValueError("verbatim max_copied_share must be within 0..1")


DEFAULT_THRESHOLDS = VerbatimThresholds()


def verbatim_thresholds(workflow: Mapping[str, object]) -> VerbatimThresholds:
    """Read ``qa_thresholds.verbatim`` from a loaded workflow definition."""
    qa = workflow.get("qa_thresholds") if isinstance(workflow, Mapping) else None
    raw = qa.get("verbatim") if isinstance(qa, Mapping) else None
    if raw is None:
        return DEFAULT_THRESHOLDS
    if not isinstance(raw, Mapping):
        raise ValueError("qa_thresholds.verbatim must be an object")
    known = set(VerbatimThresholds.__dataclass_fields__)
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"unknown qa_thresholds.verbatim key(s): {sorted(unknown)}")
    return VerbatimThresholds(**{**asdict(DEFAULT_THRESHOLDS), **dict(raw)})


def load_workspace_thresholds(
    workspace: Path, versions_dir: Path, default_version: str = "v1"
) -> VerbatimThresholds:
    """Thresholds for callers that cannot import pipeline.py (monitor, report).

    Mirrors pipeline.resolve_workspace_workflow: the manifest's
    ``workflow_version`` if present, else the default version.
    """
    version = default_version
    manifest = workspace / "workflow_manifest.json"
    if manifest.is_file():
        data = json.loads(manifest.read_text())
        version = str(data.get("workflow_version") or default_version)
    workflow = json.loads((versions_dir / version / "workflow.json").read_text())
    return verbatim_thresholds(workflow)


# ─── Prompt policy ──────────────────────────────────────────────────────────


def strategy_options(rights: str) -> str:
    strategies = _PD_STRATEGIES if rights == PUBLIC_DOMAIN else _COMMENTARY_STRATEGIES
    return " / ".join(strategies)


def render_rights_policy(rights: str, thresholds: VerbatimThresholds) -> str:
    if rights == PUBLIC_DOMAIN:
        return (
            "\n## RIGHTS POLICY — this book is `public_domain`\n\n"
            "Verbatim reading is allowed: any episode strategy may be used, "
            "including `full_text`. The code verbatim gate is exempt for "
            "public-domain books.\n"
        )
    share_pct = f"{thresholds.max_copied_share * 100:g}"
    return (
        f"\n## RIGHTS POLICY (enforced in code) — this book is `{rights}`, "
        "NOT public domain\n\n"
        "The show is transformative commentary and must never work as a substitute "
        "for the book:\n"
        f"- Allowed episode strategies: {strategy_options(rights)} — nothing else. "
        "Never plan, write, or approve a reading of the book's text at length, "
        "whatever an existing plan file says.\n"
        "- Quote sparingly: every verbatim quotation is a single sentence and stays "
        f"well under {thresholds.max_run_words} words. Paraphrase everything else "
        "in the hosts' own words.\n"
        "- A long passage split between both hosts, or broken up by audio tags or "
        "interjections, still counts as ONE verbatim quotation.\n"
        "- Hard gate: before audio synthesis and again before publishing, code "
        "compares every script and subtitle with `source/chapters/`. A verbatim run "
        f"longer than {thresholds.max_run_words} words, or more than {share_pct}% of "
        f"an episode's words inside copied runs of {thresholds.min_run_words}+ words, "
        "blocks the pipeline.\n"
    )


def render_prompt(prompt: str, rights: str, thresholds: VerbatimThresholds) -> str:
    """Fill ``{rights_policy}`` / ``{strategy_options}`` for this workspace."""
    return prompt.replace(
        "{rights_policy}", render_rights_policy(rights, thresholds)
    ).replace("{strategy_options}", strategy_options(rights))


# ─── Plan validator ─────────────────────────────────────────────────────────

_STRATEGY_LINE_RE = re.compile(
    r"^[\s>*-]*\**\s*strategy\s*\**\s*:\s*(.+)$", re.IGNORECASE
)
_FULL_TEXT_RE = re.compile(r"full[\s_-]*text", re.IGNORECASE)


def full_text_strategy_plans(workspace: Path) -> list[str]:
    """Episode plans (workspace-relative) whose Strategy line is full text."""
    hits: list[str] = []
    for plan in sorted((workspace / "plan" / "episodes").glob("ep_*.md")):
        for line in plan.read_text(encoding="utf-8", errors="replace").splitlines():
            m = _STRATEGY_LINE_RE.match(line)
            if m and _FULL_TEXT_RE.search(m.group(1)):
                hits.append(plan.relative_to(workspace).as_posix())
                break
    return hits


# ─── Text normalisation ─────────────────────────────────────────────────────

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_SOURCE_LABEL_RE = re.compile(r"\*\*[^*\n]{1,80}?(?::\*\*|\*\*\s*:)")
_SOURCE_TAG_RE = re.compile(r"\[[^\]\n]{0,80}\]")
_APOSTROPHE_RE = re.compile(r"['‘’`ʼ]")
_CJK = "぀-ヿ㐀-䶿一-鿿豈-﫿"
_TOKEN_RE = re.compile(rf"[{_CJK}]|[^\W_{_CJK}]+")


# What synthesize.parse_script does NOT voice, restated (the gate stays
# stdlib-only; test_skip_and_dialogue_patterns_mirror_synthesize pins parity with
# tts_config): structural lines are skipped whole; only a line-start ``**Name:**``
# is a speaker label; everything else on the line is spoken.
_SKIP_LINE_RE = re.compile(r"^(#{1,6}\s|>\s|---\s*$|<!--.*-->\s*$)")
_DIALOGUE_RE = re.compile(r"\*\*([^:*]+):\*\*\s*(.*)")
_BRACKET_RE = re.compile(r"\[([^\[\]]+)\]")
_SRT_SPEAKER_RE = re.compile(r"^\[[^\]\n]{1,40}\]\s*")


def _palette_forms() -> frozenset[str]:
    """Every audio-tag surface form tts_tags knows (any family).

    ``tts_tags.sanitize_tags_for_family`` rewrites or strips exactly these and keeps
    every other ``[bracket]`` as spoken content, so only these are inaudible.
    """
    from tts_tags import TAG_CONCEPTS

    return frozenset(f for c in TAG_CONCEPTS for f in c.forms.values())


_PALETTE = _palette_forms()


def _fold(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return _TOKEN_RE.findall(_APOSTROPHE_RE.sub("", text))


def _drop_palette_tags(text: str) -> str:
    return _BRACKET_RE.sub(
        lambda m: " " if m.group(1).strip().lower() in _PALETTE else m.group(0), text
    )


def tokenize_source(text: str) -> list[str]:
    """Words of the BOOK. Lenient on purpose: footnote markers (``[12]``), HTML
    comments and bold labels are never part of a quote, and dropping them can only
    make a copied passage easier to match."""
    text = _COMMENT_RE.sub(" ", text)
    text = _SOURCE_LABEL_RE.sub(" ", text)
    text = _SOURCE_TAG_RE.sub(" ", text)
    return _fold(text)


def tokenize_script(text: str) -> list[str]:
    """Words a listener would hear from a markdown script — the mirror of
    ``synthesize.parse_script``, never more lenient than it.

    Dropped: whole structural lines (headings, blockquotes, rules, whole-line HTML
    comments), a line-start ``**Name:**`` label, and palette audio tags
    (``[slow]`` ...), so a passage split between hosts or broken by a tag is still
    one run. Everything else is voiced and therefore measured: a non-palette
    ``[bracket]``, an inline comment after the label, a mid-line ``**x:**``.
    Case, accents, punctuation and apostrophes are folded; CJK is one token per
    character.
    """
    spoken: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or _SKIP_LINE_RE.match(stripped):
            continue
        m = _DIALOGUE_RE.match(stripped)
        spoken.append(_drop_palette_tags(m.group(2) if m else stripped))
    return _fold(" ".join(spoken))


def srt_text(raw: str) -> str:
    """Spoken text of an SRT: cue numbers, timestamps and the ``[Speaker]`` prefix
    subtitle.py puts at the start of a cue are removed."""
    lines = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.isdigit() or "-->" in s:
            continue
        lines.append(_SRT_SPEAKER_RE.sub("", s))
    return " ".join(lines)


def tokenize_subtitle(raw: str) -> list[str]:
    return _fold(srt_text(raw))


# ─── Overlap measurement ────────────────────────────────────────────────────

_SHINGLE_WORDS = 6
# A shingle repeated more often than this in the book is boilerplate; extra
# occurrences add nothing but cost.
_MAX_POSITIONS = 64


class SourceIndex:
    """Shingle index over the book's tokens."""

    def __init__(self, tokens: list[str], shingle: int):
        self.tokens = tokens
        self.k = shingle
        index: dict[tuple[str, ...], list[int]] = {}
        for j in range(len(tokens) - shingle + 1):
            key = tuple(tokens[j : j + shingle])
            positions = index.get(key)
            if positions is None:
                index[key] = [j]
            elif len(positions) < _MAX_POSITIONS:
                positions.append(j)
        self.index = index

    @classmethod
    def from_texts(
        cls, texts: Iterable[str], thresholds: VerbatimThresholds
    ) -> SourceIndex:
        tokens: list[str] = []
        for text in texts:
            tokens.extend(tokenize_source(text))
        return cls(tokens, min(_SHINGLE_WORDS, thresholds.min_run_words))


@dataclass
class OverlapResult:
    words: int
    longest_run: int
    copied_words: int
    copied_share: float
    excerpt: str


def _exact_segments(
    script: list[str], source: SourceIndex
) -> list[tuple[int, int, int, int]]:
    """Maximal exact common runs as (script_start, script_end, src_start, src_end)."""
    k = source.k
    n = len(script)
    segments: list[tuple[int, int, int, int]] = []
    prev: dict[int, tuple[int, int]] = {}
    for i in range(n - k + 1):
        cur: dict[int, tuple[int, int]] = {}
        for p in source.index.get(tuple(script[i : i + k]), ()):
            cur[p] = prev.get(p - 1) or (i, p)
        for p_last, (s0, p0) in prev.items():
            if p_last + 1 not in cur:
                segments.append((s0, i - 1 + k, p0, p_last + k))
        prev = cur
    for p_last, (s0, p0) in prev.items():
        segments.append((s0, n, p0, p_last + k))
    return segments


def _merge_runs(
    segments: list[tuple[int, int, int, int]], gap: int, k: int
) -> list[tuple[int, int]]:
    """Chain exact segments that continue the same book passage within ``gap``."""
    segments.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    runs: list[list[int]] = []  # [script_start, script_end, src_end]
    active: list[list[int]] = []
    for s0, s1, p0, p1 in segments:
        active = [r for r in active if r[1] >= s0 - gap]
        for run in active:
            ds, dp = s0 - run[1], p0 - run[2]
            if -k < ds <= gap and -k < dp <= gap and abs(ds - dp) <= gap:
                run[1] = max(run[1], s1)
                run[2] = max(run[2], p1)
                break
        else:
            run = [s0, s1, p1]
            runs.append(run)
            active.append(run)
    return [(r[0], r[1]) for r in runs]


def measure_overlap(
    tokens: list[str], source: SourceIndex, thresholds: VerbatimThresholds
) -> OverlapResult:
    runs = _merge_runs(_exact_segments(tokens, source), thresholds.gap_words, source.k)
    longest = max(runs, key=lambda r: r[1] - r[0], default=(0, 0))
    covered = [False] * len(tokens)
    for s0, s1 in runs:
        if s1 - s0 >= thresholds.min_run_words:
            covered[s0:s1] = [True] * (s1 - s0)
    copied = sum(covered)
    excerpt_words = tokens[longest[0] : longest[1]]
    excerpt = " ".join(excerpt_words[:16]) + (" …" if len(excerpt_words) > 16 else "")
    return OverlapResult(
        words=len(tokens),
        longest_run=longest[1] - longest[0],
        copied_words=copied,
        copied_share=round(copied / len(tokens), 4) if tokens else 0.0,
        excerpt=excerpt,
    )


# ─── Workspace gate ─────────────────────────────────────────────────────────

_EP_RE = re.compile(r"^ep_(\d+)_")
_AUDIO_RE = re.compile(r"^ep_(\d+)_[A-Za-z]+\.(?:mp3|m4a)$")


@dataclass
class TextResult:
    artifact: str
    episode: int | None
    kind: str
    words: int
    longest_run: int
    copied_words: int
    copied_share: float
    excerpt: str
    violations: list[str] = field(default_factory=list)


@dataclass
class GateReport:
    stage: str
    rights: str
    blocked: bool
    thresholds: dict
    reasons: list[str] = field(default_factory=list)
    texts: list[TextResult] = field(default_factory=list)
    validator_version: str = VALIDATOR_VERSION
    checked_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        parts = list(self.reasons)
        for t in self.texts:
            if t.violations:
                parts.append(f"{t.artifact}: {'; '.join(t.violations)}")
        return " | ".join(parts) if parts else "no violations"


def _episode(name: str) -> int | None:
    m = _EP_RE.match(name)
    return int(m.group(1)) if m else None


def _texts_for_stage(
    workspace: Path, stage: str, only_episode: int | None
) -> tuple[list[tuple[Path, str]], list[str]]:
    scripts_dir = workspace / "scripts"
    texts: list[tuple[Path, str]] = []
    reasons: list[str] = []
    scripts = sorted(scripts_dir.glob("ep_*_script.md"))
    if only_episode is not None:
        scripts = [p for p in scripts if _episode(p.name) == only_episode]
    texts += [(p, "script") for p in scripts]
    if stage == "publish":
        srts = sorted(scripts_dir.glob("ep_*.srt"))
        texts += [(p, "subtitle") for p in srts]
        measured = {_episode(p.name) for p, _ in texts}
        audio_eps = sorted(
            {
                int(m.group(1))
                for p in scripts_dir.glob("ep_*")
                if (m := _AUDIO_RE.match(p.name))
            }
        )
        for ep in audio_eps:
            if ep not in measured:
                reasons.append(
                    f"episode {ep} has audio but no script or subtitle to verify"
                )
    if not texts:
        reasons.append("no script/subtitle text found to verify")
    return texts, reasons


def check_workspace(
    workspace: Path,
    *,
    stage: str,
    thresholds: VerbatimThresholds,
    only_episode: int | None = None,
) -> GateReport:
    """Measure the texts ``stage`` would ship against ``source/chapters``.

    ``stage="synthesize"`` checks the scripts to be voiced; ``stage="publish"``
    checks every script AND subtitle that would be uploaded, and requires a text
    for every episode that has audio. Public-domain books are never blocked;
    everything else fails closed on a missing source, a missing text or an
    unreadable sidecar.
    """
    try:
        rights = read_rights(workspace)
    except RightsError as exc:
        return GateReport(
            stage=stage,
            rights="unreadable",
            blocked=True,
            thresholds=asdict(thresholds),
            reasons=[str(exc)],
        )
    texts, reasons = _texts_for_stage(workspace, stage, only_episode)
    chapters = sorted((workspace / "source" / "chapters").glob("ch_*.md"))
    if not chapters:
        reasons.append(
            "source/chapters/ch_*.md missing — verbatim overlap cannot be verified"
        )
    source = SourceIndex.from_texts(
        (c.read_text(encoding="utf-8", errors="replace") for c in chapters),
        thresholds,
    )
    results: list[TextResult] = []
    if source.tokens:
        for path, kind in texts:
            raw = path.read_text(encoding="utf-8", errors="replace")
            tokens = (
                tokenize_subtitle(raw) if kind == "subtitle" else tokenize_script(raw)
            )
            r = measure_overlap(tokens, source, thresholds)
            violations = []
            if r.longest_run > thresholds.max_run_words:
                violations.append(
                    f"longest verbatim run {r.longest_run} words > max_run_words "
                    f"{thresholds.max_run_words}"
                )
            if r.copied_share > thresholds.max_copied_share:
                violations.append(
                    f"copied share {r.copied_share:.1%} > max_copied_share "
                    f"{thresholds.max_copied_share:.1%}"
                )
            results.append(
                TextResult(
                    artifact=path.relative_to(workspace).as_posix(),
                    episode=_episode(path.name),
                    kind=kind,
                    words=r.words,
                    longest_run=r.longest_run,
                    copied_words=r.copied_words,
                    copied_share=r.copied_share,
                    excerpt=r.excerpt,
                    violations=violations,
                )
            )
    elif not any("source/chapters" in reason for reason in reasons):
        reasons.append("source/chapters contain no text — overlap cannot be verified")
    exempt = rights == PUBLIC_DOMAIN
    blocked = not exempt and (bool(reasons) or any(t.violations for t in results))
    return GateReport(
        stage=stage,
        rights=rights,
        blocked=blocked,
        thresholds=asdict(thresholds),
        reasons=reasons,
        texts=results,
    )


EXEMPT_REASON = "public_domain — verbatim gate exempt"


def evaluate_gate(
    workspace: Path,
    *,
    stage: str,
    load_thresholds: Callable[[], VerbatimThresholds],
    only_episode: int | None = None,
) -> GateReport:
    """The one gate decision shared by pipeline stages and the dashboard upload.

    Fails closed (blocked report) on an unreadable sidecar or invalid
    thresholds; public domain is exempt without measuring.
    """
    try:
        rights = read_rights(workspace)
    except RightsError as exc:
        return GateReport(
            stage=stage,
            rights="unreadable",
            blocked=True,
            thresholds={},
            reasons=[str(exc)],
        )
    if rights == PUBLIC_DOMAIN:
        return GateReport(
            stage=stage,
            rights=rights,
            blocked=False,
            thresholds={},
            reasons=[EXEMPT_REASON],
        )
    try:
        thresholds = load_thresholds()
    except (OSError, ValueError) as exc:
        return GateReport(
            stage=stage,
            rights=rights,
            blocked=True,
            thresholds={},
            reasons=[f"invalid verbatim thresholds: {exc}"],
        )
    return check_workspace(
        workspace, stage=stage, thresholds=thresholds, only_episode=only_episode
    )


def write_report(path: Path, report: GateReport) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


# ─── Read-only report over existing workspaces ──────────────────────────────


def _workspace_report(ws: Path, versions_dir: Path) -> dict:
    try:
        thresholds = load_workspace_thresholds(ws, versions_dir)
        threshold_error = None
    except (OSError, ValueError) as exc:
        thresholds, threshold_error = DEFAULT_THRESHOLDS, str(exc)
    sidecar = ws / RIGHTS_SIDECAR
    scripts_dir = ws / "scripts"
    audio = sorted(p.name for p in scripts_dir.glob("ep_*") if _AUDIO_RE.match(p.name))
    gate = check_workspace(ws, stage="publish", thresholds=thresholds)
    scripts = [t for t in gate.texts if t.kind == "script"]
    return {
        "workspace": ws.name,
        "rights": gate.rights,
        "rights_source": "sidecar" if sidecar.is_file() else "default (no sidecar)",
        "published_marker": (ws / ".stage_publish_done").is_file(),
        "synthesized_marker": (ws / ".stage_synthesize_done").is_file(),
        "audio_files": len(audio),
        "subtitle_files": len(list(scripts_dir.glob("ep_*.srt"))),
        "script_files": len(scripts),
        "full_text_plans": full_text_strategy_plans(ws),
        "thresholds": asdict(thresholds),
        "threshold_error": threshold_error,
        "max_run_script": max((t.longest_run for t in scripts), default=0),
        "copied_words_script": sum(t.copied_words for t in scripts),
        "words_script": sum(t.words for t in scripts),
        "max_share_script": max((t.copied_share for t in scripts), default=0.0),
        "would_block_publish": gate.blocked,
        "gate": gate.to_dict(),
    }


def report_workspaces(workspaces_dir: Path, versions_dir: Path) -> dict:
    rows = [
        _workspace_report(ws, versions_dir)
        for ws in sorted(p for p in workspaces_dir.iterdir() if p.is_dir())
    ]
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "workspaces_dir": str(workspaces_dir),
        "default_thresholds": asdict(DEFAULT_THRESHOLDS),
        "workspaces": rows,
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Verbatim / rights report",
        "",
        f"- generated: {report['generated_at']}",
        f"- workspaces dir: `{report['workspaces_dir']}`",
        f"- default thresholds: `{json.dumps(report['default_thresholds'])}`",
        "",
        (
            "| workspace | rights | published | audio | full_text plans "
            "| max run (script) | copied words / words (script) | max ep share "
            "| publish gate |"
        ),
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in report["workspaces"]:
        share_total = (
            r["copied_words_script"] / r["words_script"] if r["words_script"] else 0.0
        )
        lines.append(
            f"| {r['workspace']} | {r['rights']} ({r['rights_source']}) "
            f"| {'yes' if r['published_marker'] else 'no'} | {r['audio_files']} "
            f"| {len(r['full_text_plans'])} | {r['max_run_script']} "
            f"| {r['copied_words_script']:,} / {r['words_script']:,} ({share_total:.1%}) "
            f"| {r['max_share_script']:.1%} "
            f"| {'BLOCK' if r['would_block_publish'] else 'pass'} |"
        )
    lines.append("")
    for r in report["workspaces"]:
        lines.append(f"## {r['workspace']}")
        lines.append("")
        if r["full_text_plans"]:
            lines.append(f"- full_text plans: {', '.join(r['full_text_plans'])}")
        for reason in r["gate"]["reasons"]:
            lines.append(f"- gate reason: {reason}")
        lines.append("")
        lines.append("| artifact | words | longest run | copied | share | violations |")
        lines.append("|---|---|---|---|---|---|")
        for t in r["gate"]["texts"]:
            lines.append(
                f"| {t['artifact']} | {t['words']:,} | {t['longest_run']} "
                f"| {t['copied_words']} | {t['copied_share']:.1%} "
                f"| {'; '.join(t['violations']) or '—'} |"
            )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    rep = sub.add_parser("report", help="read-only verbatim/rights report")
    rep.add_argument("workspaces_dir", type=Path)
    rep.add_argument(
        "--versions-dir",
        type=Path,
        default=Path(__file__).parent / "workflow_versions",
    )
    rep.add_argument("--json", type=Path, help="write the full JSON report here")
    rep.add_argument("--md", type=Path, help="write the markdown summary here")
    args = parser.parse_args(argv)
    if not args.workspaces_dir.is_dir():
        print(f"not a directory: {args.workspaces_dir}", file=sys.stderr)
        return 3
    report = report_workspaces(args.workspaces_dir, args.versions_dir)
    markdown = render_markdown(report)
    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if args.md:
        args.md.write_text(markdown + "\n")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
