"""Archetype registry + prompt-resolver + sidecar tests (Phase 0 foundation).

Guards the two correctness properties the whole archetype system rests on:

1. The resolver falls through to the BASE prompt unless a variant file exists —
   so `nonfiction` (suffix=None) provably never changes existing behavior, and
   an archetype only forks the stages it ships a variant for.
2. The mode/spoiler sidecars are the resume source of truth — written on fresh
   setup, re-read on resume, never silently mixing prompt sets.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import archetypes
import pipeline


def test_default_is_nonfiction_with_no_suffix() -> None:
    assert archetypes.DEFAULT_ARCHETYPE == "nonfiction"
    assert archetypes.get("nonfiction")["suffix"] is None


def test_unknown_archetype_falls_back_to_default() -> None:
    assert archetypes.get("does-not-exist") == archetypes.ARCHETYPES["nonfiction"]


def test_every_spoiler_archetype_lists_modes() -> None:
    for name, entry in archetypes.ARCHETYPES.items():
        if entry["requires_spoiler_policy"]:
            assert entry["spoiler_modes"], f"{name} requires spoiler policy but lists no modes"
        else:
            assert entry["spoiler_modes"] == [], f"{name} should list no spoiler modes"


def test_saga_is_multi_book_and_reuses_fiction_prompts() -> None:
    assert "saga" in archetypes.MULTI_BOOK_ARCHETYPES
    # saga reuses the fiction prompt set rather than duplicating it
    assert archetypes.get("saga")["suffix"] == "fiction"


@pytest.mark.parametrize(
    "archetype,mode,ok",
    [
        ("nonfiction", None, True),
        ("nonfiction", "readalong", False),  # nonfiction takes no spoiler mode
        ("fiction", None, False),  # fiction requires a mode
        ("fiction", "readalong", True),
        ("fiction", "retrospective", True),
        ("fiction", "bogus", False),
        ("saga", "readalong", True),
        ("saga", None, False),
    ],
)
def test_validate_spoiler_mode(archetype: str, mode: str | None, ok: bool) -> None:
    err = archetypes.validate_spoiler_mode(archetype, mode)
    assert (err is None) == ok, err


# ─── Resolver ───


def test_resolver_falls_through_to_base_when_no_variant() -> None:
    # nonfiction has suffix=None → always base prompt.
    base = pipeline._prompt("analyst", "nonfiction")
    assert base == (pipeline.PROMPTS_DIR / "analyst.md").read_text()


def test_resolver_falls_through_when_variant_missing() -> None:
    # fiction has suffix "fiction" but if analyst_fiction.md doesn't exist yet
    # (Phase 0 ships no variants), it must fall through to base, not crash.
    variant = pipeline.PROMPTS_DIR / "analyst_fiction.md"
    if variant.exists():
        pytest.skip("analyst_fiction.md exists — fall-through case not testable here")
    assert pipeline._prompt("analyst", "fiction") == (pipeline.PROMPTS_DIR / "analyst.md").read_text()


def test_resolver_prefers_variant_when_present(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(pipeline, "PROMPTS_DIR", tmp_path)
    (tmp_path / "analyst.md").write_text("BASE")
    (tmp_path / "analyst_fiction.md").write_text("FICTION VARIANT")
    assert pipeline._prompt("analyst", "fiction") == "FICTION VARIANT"
    assert pipeline._prompt("analyst", "nonfiction") == "BASE"


# ─── Sidecars ───


def test_sidecar_roundtrip(tmp_path: Path) -> None:
    pipeline.write_mode_sidecar(tmp_path, "fiction", "readalong")
    assert pipeline.read_mode(tmp_path) == "fiction"
    assert pipeline.read_spoiler_mode(tmp_path) == "readalong"


def test_read_mode_defaults_to_nonfiction_when_absent(tmp_path: Path) -> None:
    # Legacy workspaces created before archetypes existed have no .mode sidecar.
    assert pipeline.read_mode(tmp_path) == "nonfiction"
    assert pipeline.read_spoiler_mode(tmp_path) is None


def test_sidecar_omits_spoiler_for_nonfiction(tmp_path: Path) -> None:
    pipeline.write_mode_sidecar(tmp_path, "nonfiction", None)
    assert pipeline.read_mode(tmp_path) == "nonfiction"
    assert not (tmp_path / ".spoiler_mode").exists()
