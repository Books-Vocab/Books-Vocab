#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "ebooklib",
#     "beautifulsoup4",
#     "pytest",
# ]
# ///
from __future__ import annotations

import json
from pathlib import Path
import types

import pytest

import pipeline


class _FakeLog:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def event(self, msg, **kw) -> None:
        self.messages.append(msg)

    def error(self, msg, **kw) -> None:
        self.messages.append(f"ERROR: {msg}")


def test_workflow_versions_are_discoverable() -> None:
    assert {"v1", "v2"}.issubset(set(pipeline.available_workflow_versions()))
    assert pipeline.load_workflow_definition("v1")["workflow_version"] == "v1"


def test_write_workflow_manifest_records_reproducibility_fields(tmp_path, monkeypatch) -> None:
    ws = tmp_path / "ws"
    (ws / "plan" / "episodes").mkdir(parents=True)
    (ws / "scripts").mkdir()
    monkeypatch.setattr(pipeline, "_pipeline_commit", lambda: "abc123")

    manifest = pipeline.write_workflow_manifest(
        ws,
        workflow_version="v1",
        agent_profile="claude",
        agent_model="opus[1m]",
        tts_model="gemini-2.5-flash-tts",
    )

    on_disk = json.loads((ws / "workflow_manifest.json").read_text())
    assert on_disk == manifest
    assert manifest["workflow_version"] == "v1"
    assert manifest["pipeline_commit"] == "abc123"
    assert manifest["agent_profile"] == "claude"
    assert manifest["agent_model"] == "opus[1m]"
    assert manifest["tts_model"] == "gemini-2.5-flash-tts"
    assert manifest["prompt_fingerprints"]
    assert manifest["validator_versions"]
    assert manifest["stage_contracts"]["stage_order"] == pipeline.workflow_stage_order("v1")
    assert "created_at" in manifest


def test_write_workflow_manifest_does_not_rewrite_existing_manifest(tmp_path, monkeypatch) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    original = {
        "workflow_version": "v1",
        "pipeline_commit": "old",
        "prompt_fingerprints": {"prompts/prep.md": "oldhash"},
        "created_at": "2026-01-01T00:00:00",
    }
    (ws / "workflow_manifest.json").write_text(json.dumps(original))
    monkeypatch.setattr(pipeline, "_pipeline_commit", lambda: "new")

    manifest = pipeline.write_workflow_manifest(
        ws,
        workflow_version="v1",
        agent_profile="claude",
        agent_model="opus[1m]",
        tts_model="gemini-2.5-flash-tts",
    )

    assert manifest == original
    assert json.loads((ws / "workflow_manifest.json").read_text()) == original


def test_existing_workflow_manifest_rejects_conflicting_resume(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "workflow_manifest.json").write_text(json.dumps({"workflow_version": "v1"}))

    assert pipeline.resolve_workspace_workflow(ws, None) == "v1"
    try:
        pipeline.resolve_workspace_workflow(ws, "v2")
    except ValueError as e:
        assert "workflow_version v1" in str(e)
    else:
        raise AssertionError("conflicting workflow version should fail")


def test_stage_provenance_records_hashes_and_lineage(tmp_path, monkeypatch) -> None:
    ws = tmp_path / "ws"
    scripts = ws / "scripts"
    scripts.mkdir(parents=True)
    (ws / "workflow_manifest.json").write_text(json.dumps({"workflow_version": "v1"}))
    script = scripts / "ep_1_script.md"
    script.write_text("old draft\n")
    monkeypatch.setattr(pipeline, "_pipeline_commit", lambda: "abc123")

    before = pipeline.capture_stage_inputs(ws, "series-polish", only_episode=None)
    script.write_text("polished draft\nEND_OF_SCRIPT\n")
    pipeline.write_stage_provenance(
        ws,
        stage="series-polish",
        success=True,
        elapsed_s=1.2,
        input_artifacts=before,
        only_episode=None,
    )

    prov = json.loads((ws / "stage_provenance" / "series-polish.json").read_text())
    assert prov["stage"] == "series-polish"
    assert prov["workflow_version"] == "v1"
    assert prov["input_artifacts"]["scripts/ep_1_script.md"]["sha256"]
    assert prov["output_artifacts"]["scripts/ep_1_script.md"]["sha256"]
    assert prov["output_artifacts"]["scripts/ep_1_script.md"]["sha256"] != prov["input_artifacts"]["scripts/ep_1_script.md"]["sha256"]
    assert prov["prompt"]["version"] == "v1"
    assert prov["model"]["agent_profile"] == pipeline.AGENT_PROFILE
    assert prov["pipeline_commit"] == "abc123"

    lineage = json.loads((scripts / "ep_1_lineage.json").read_text())
    assert lineage["episode"] == 1
    assert lineage["workflow_version"] == "v1"
    assert lineage["series_polish"][0]["before_hash"]
    assert lineage["series_polish"][0]["after_hash"]
    assert lineage["series_polish"][0]["changed"] is True


def test_stage_provenance_records_cost_event_refs(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "workflow_manifest.json").write_text(json.dumps({"workflow_version": "v1"}))
    (ws / "events.jsonl").write_text(
        json.dumps({
            "stage_label": "Scriptwriter EP1",
            "event": {"type": "result", "modelUsage": {"opus": {"costUSD": 0.12}}},
        })
        + "\n"
    )

    prov = pipeline.write_stage_provenance(
        ws,
        stage="scriptwrite",
        success=True,
        elapsed_s=0.1,
        input_artifacts={},
        only_episode=None,
    )

    assert prov["cost_event_ids"] == ["events.jsonl:1"]


def test_audio_qa_strict_policy_drives_stage_command(tmp_path, monkeypatch) -> None:
    ws = tmp_path / "ws"
    (ws / "scripts").mkdir(parents=True)
    (ws / "workflow_manifest.json").write_text(json.dumps({"workflow_version": "v1"}))
    (ws / "scripts" / "ep_1_pro.mp3").write_bytes(b"fake")
    monkeypatch.setattr(
        pipeline,
        "load_workflow_definition",
        lambda version: {
            "workflow_version": version,
            "qa_thresholds": {"audio-qa": {"strict": True}},
        },
    )
    box = {}

    def fake_run(cmd, **kwargs):
        box["cmd"] = cmd
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)

    assert pipeline.stage_audio_qa(ws, _FakeLog()) is True
    assert "--strict" in box["cmd"]


def test_audio_qa_strict_policy_marks_warn_report_failed(tmp_path, monkeypatch) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "workflow_manifest.json").write_text(json.dumps({"workflow_version": "v1"}))
    (ws / "audio_qa.json").write_text(json.dumps({"summary": {"pass": 0, "warn": 1, "fail": 0}}))
    monkeypatch.setattr(
        pipeline,
        "load_workflow_definition",
        lambda version: {
            "workflow_version": version,
            "qa_thresholds": {"audio-qa": {"strict": True}},
        },
    )

    prov = pipeline.write_stage_provenance(
        ws,
        stage="audio-qa",
        success=False,
        elapsed_s=0.1,
        input_artifacts={},
        only_episode=None,
    )

    assert prov["validator_result"]["strict"] is True
    assert prov["validator_result"]["status"] == "fail"


def test_prompt_resolution_uses_versioned_snapshot() -> None:
    current = (Path(pipeline.ROOT) / "prompts" / "prep.md").read_text()
    snap = pipeline.prompt_text("prep", pipeline.archetypes.DEFAULT_ARCHETYPE, "v1")
    assert snap == current


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
