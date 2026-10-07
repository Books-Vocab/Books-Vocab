"""Tests for the unified CLI dispatcher."""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from llm_eval.cli import main

# Derived from this file, not from the code under test.
_LAB_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _LAB_ROOT.parents[1]
_PACKAGE_RESULTS = _LAB_ROOT / "results"


def test_no_subcommand_prints_help(capsys):
    code = main([])
    assert code == 2
    assert "llm-eval" in capsys.readouterr().out


def test_help_shows_subcommands(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    for cmd in (
        "eval",
        "prompts",
        "datasets",
        "providers",
        "corpus-build",
        "gold-queue",
    ):
        assert cmd in out


def test_prompts_list(capsys):
    code = main(["prompts"])
    assert code == 0
    out = capsys.readouterr().out
    assert "translate_quick" in out


def test_prompts_list_json(capsys):
    code = main(["prompts", "--json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    names = [item["name"] for item in data]
    assert "translate_quick" in names


def test_prompts_detail_json(capsys):
    code = main(["prompts", "--name", "translate_quick", "--json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["name"] == "translate_quick"
    assert "schema" in data


def test_prompts_unknown_name(capsys):
    code = main(["prompts", "--name", "nonexistent_prompt"])
    assert code == 1
    assert "Error" in capsys.readouterr().err


def test_datasets_list(capsys):
    code = main(["datasets"])
    assert code == 0
    out = capsys.readouterr().out
    assert "translate_quick" in out


def test_datasets_list_json(capsys):
    code = main(["datasets", "--json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert any(d["name"] == "translate_quick" for d in data)
    assert all("rows" in d for d in data)


def test_datasets_detail_json(capsys):
    code = main(["datasets", "--name", "translate_quick", "--json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["name"] == "translate_quick"
    assert data["rows"] > 0
    assert "preview" in data
    assert len(data["preview"]) <= 3


def test_datasets_unknown_name(capsys):
    code = main(["datasets", "--name", "nonexistent_dataset"])
    assert code == 1
    assert "Error" in capsys.readouterr().err


def test_providers_list(capsys):
    code = main(["providers"])
    assert code == 0
    out = capsys.readouterr().out
    assert "ollama" in out


def test_providers_list_json(capsys):
    code = main(["providers", "--json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    names = [p["name"] for p in data]
    assert "ollama" in names


def test_eval_requires_args(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["eval"])
    assert exc_info.value.code == 2


def _write_report(tmp_path, dataset_name="translate_quick_gold"):
    report = {
        "timestamp": "20260101T000000Z",
        "prompt": {"name": "translate_quick", "version": "v1"},
        "dataset_name": dataset_name,
        "models": {
            "deepseek-v4-flash": {
                "provider": "deepseek",
                "samples": [
                    {
                        "sample_id": "s1",
                        "parsed_output": {"t": "喚起", "p": "v.", "r": "evoke"},
                        "raw_output": '{"t":"喚起","p":"v.","r":"evoke"}',
                        "scores": {"json_valid": 1.0, "schema_conform": 1.0},
                        "error": None,
                    }
                ],
            }
        },
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return path


def test_review_json_joins_output(tmp_path, capsys):
    path = _write_report(tmp_path, dataset_name="nonexistent_dataset")
    code = main(["review", "--results", str(path), "--json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["header"]["model"] == "deepseek-v4-flash"
    assert len(data["records"]) == 1
    rec = data["records"][0]
    assert rec["id"] == "s1"
    assert rec["llm"]["t"] == "喚起"
    assert rec["format"]["json_valid"] == 1.0


def test_review_range_slice(tmp_path, capsys):
    path = _write_report(tmp_path, dataset_name="nonexistent_dataset")
    code = main(["review", "--results", str(path), "--range", "1:5", "--json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["records"] == []


def test_review_missing_report(capsys):
    code = main(["review", "--results", "/nonexistent/report.json"])
    assert code == 1
    assert "no matching report" in capsys.readouterr().err


def test_review_markdown_default(tmp_path, capsys):
    path = _write_report(tmp_path, dataset_name="nonexistent_dataset")
    code = main(["review", "--results", str(path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "# Review" in out
    assert "s1" in out
    assert "llm:" in out


def _report(prompt: str, dataset: str, timestamp: str) -> dict:
    return {
        "timestamp": timestamp,
        "prompt": {"name": prompt, "version": "v1"},
        "dataset_name": dataset,
        "models": {"deepseek-v4-flash": {"provider": "deepseek", "samples": []}},
    }


def _put_report(directory: Path, prompt: str, dataset: str, timestamp: str) -> Path:
    """Write a report under the same filename scheme as ``write_report``."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{timestamp}_{prompt}_{dataset}.json"
    path.write_text(json.dumps(_report(prompt, dataset, timestamp)), encoding="utf-8")
    return path


@pytest.fixture
def package_results_cleanup():
    """Paths a test writes into the real ``<package>/results`` (git-ignored);
    removed afterwards, along with the directory if the test created it."""
    existed = _PACKAGE_RESULTS.exists()
    written: list[Path] = []
    yield written
    for path in written:
        path.unlink(missing_ok=True)
    if (
        not existed
        and _PACKAGE_RESULTS.exists()
        and not any(_PACKAGE_RESULTS.iterdir())
    ):
        _PACKAGE_RESULTS.rmdir()


@pytest.mark.parametrize("cwd", ["package_root", "repo_root", "elsewhere"])
def test_review_default_results_dir_resolves_against_package_root(
    cwd, tmp_path, monkeypatch, capsys, package_results_cleanup
):
    """The documented `cd lab/llm_eval && review`, the repo root and any other
    cwd must all search <package>/results."""
    prompt = f"cwd_probe_{uuid.uuid4().hex}"
    path = _put_report(
        _PACKAGE_RESULTS, prompt, "nonexistent_dataset", "29991231T235959Z"
    )
    package_results_cleanup.append(path)
    monkeypatch.chdir(
        {"package_root": _LAB_ROOT, "repo_root": _REPO_ROOT, "elsewhere": tmp_path}[cwd]
    )

    code = main(["review", "--prompt", prompt, "--json"])

    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert Path(json.loads(captured.out)["header"]["report"]) == path


def test_review_selects_by_report_prompt_name_not_filename_substring(tmp_path, capsys):
    """`--prompt judge_batch` must not pick the newer judge_selective report
    whose filename `…_judge_selective_judge_batch_gold.json` contains it."""
    wanted = _put_report(
        tmp_path, "judge_batch", "judge_batch_gold", "20260101T000000Z"
    )
    _put_report(tmp_path, "judge_selective", "judge_batch_gold", "20260102T000000Z")

    code = main(
        ["review", "--results-dir", str(tmp_path), "--prompt", "judge_batch", "--json"]
    )

    assert code == 0
    header = json.loads(capsys.readouterr().out)["header"]
    assert Path(header["report"]) == wanted
    assert header["prompt"] == "judge_batch@v1"


def test_review_selects_by_report_dataset_name_not_filename_suffix(tmp_path, capsys):
    _put_report(tmp_path, "translate_quick", "translate_quick_gold", "20260101T000000Z")

    code = main(["review", "--results-dir", str(tmp_path), "--dataset", "quick_gold"])

    assert code == 1
    assert "no matching report" in capsys.readouterr().err


def test_review_newest_matching_report_wins_and_non_reports_are_skipped(
    tmp_path, capsys
):
    _put_report(tmp_path, "translate_quick", "translate_quick", "20260101T000000Z")
    newest = _put_report(
        tmp_path, "translate_quick", "translate_quick", "20260102T000000Z"
    )
    (tmp_path / "zz_not_json.json").write_text("{oops", encoding="utf-8")
    (tmp_path / "zz_not_a_report.json").write_text("[1, 2]", encoding="utf-8")

    code = main(["review", "--results-dir", str(tmp_path), "--json"])

    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert Path(json.loads(captured.out)["header"]["report"]) == newest


_GOOD = '{"t":"輝煌的","p":"adj.","r":"resplendent"}'
# list-shaped output fails translate_quick's dict schema → format 0.5
_SCHEMA_FAIL = '[{"t":"輝煌的","p":"adj.","r":"resplendent"}]'
_MODEL = "gemini-2.5-flash-lite"


def _response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    return resp


def _patch_client(outcomes):
    """Fake async client: each create() call consumes the next outcome
    (a response content string, or an exception instance to raise)."""
    queue = list(outcomes)
    calls: list[str] = []

    async def _create(**kwargs):
        calls.append(kwargs["model"])
        outcome = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(outcome, BaseException):
            raise outcome
        return _response(outcome)

    def _factory(provider):
        client = MagicMock()
        client.chat.completions.create = _create
        return client

    return patch(
        "llm_eval.runner.create_eval_async_client", side_effect=_factory
    ), calls


def _eval_args(*extra: str, models: str = _MODEL) -> list[str]:
    return [
        "eval",
        "--prompt",
        "translate_quick",
        "--dataset",
        "translate_quick",
        "--models",
        models,
        "--limit",
        "2",
        "--concurrency",
        "1",
        "--json",
        *extra,
    ]


def test_eval_success_exits_zero(capsys):
    patcher, calls = _patch_client([_GOOD])
    with patcher:
        code = main(_eval_args())
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["models"][_MODEL]["errors"] == 0
    assert data["failures"] == []
    assert len(calls) == 2


def test_eval_partial_sample_errors_still_exit_zero(capsys):
    """Some failed samples are a recorded result, not a failed run."""
    patcher, _ = _patch_client([RuntimeError("boom"), _GOOD])
    with patcher:
        code = main(_eval_args())
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["models"][_MODEL]["errors"] == 1


def test_eval_all_samples_errored_exits_nonzero(capsys):
    patcher, _ = _patch_client([RuntimeError("boom")])
    with patcher:
        code = main(_eval_args())
    captured = capsys.readouterr()
    assert code == 1
    data = json.loads(captured.out)
    assert data["models"][_MODEL]["errors"] == 2
    assert "all 2 samples errored" in captured.err


def test_eval_all_models_unknown_exits_nonzero_without_calls(capsys):
    patcher, calls = _patch_client([_GOOD])
    with patcher:
        code = main(_eval_args(models="no-such-model"))
    assert code == 1
    assert "no-such-model" in capsys.readouterr().err
    assert calls == []


def test_eval_one_unknown_model_fails_fast_before_spending(capsys):
    patcher, calls = _patch_client([_GOOD])
    with patcher:
        code = main(_eval_args(models=f"{_MODEL},no-such-model"))
    assert code == 1
    assert "no-such-model" in capsys.readouterr().err
    assert calls == []


def _write_baseline(tmp_path, format_score: float):
    path = tmp_path / "baseline.json"
    path.write_text(
        json.dumps({"models": {_MODEL: {"format_score_avg": format_score}}}),
        encoding="utf-8",
    )
    return path


def test_eval_baseline_regression_exits_nonzero(tmp_path, capsys):
    baseline = _write_baseline(tmp_path, 1.0)
    patcher, _ = _patch_client([_SCHEMA_FAIL])
    with patcher:
        code = main(_eval_args("--baseline", str(baseline)))
    captured = capsys.readouterr()
    assert code == 1
    data = json.loads(captured.out)
    assert data["baseline_comparison"][_MODEL]["format_regression"] is True
    assert "regression" in captured.err


def test_eval_baseline_without_regression_exits_zero(tmp_path, capsys):
    baseline = _write_baseline(tmp_path, 1.0)
    patcher, _ = _patch_client([_GOOD])
    with patcher:
        code = main(_eval_args("--baseline", str(baseline)))
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["baseline_comparison"][_MODEL]["format_regression"] is False


def test_eval_missing_baseline_fails_before_spending(tmp_path, capsys):
    patcher, calls = _patch_client([_GOOD])
    with patcher:
        code = main(_eval_args("--baseline", str(tmp_path / "missing.json")))
    assert code == 1
    assert "baseline" in capsys.readouterr().err
    assert calls == []


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"prompt": {}},
        {"models": []},
        {"models": {_MODEL: []}},
        {"models": {_MODEL: {"format_score_avg": "high"}}},
        {"models": {_MODEL: {"quality_score_avg": [1.0]}}},
    ],
)
def test_eval_malformed_baseline_shape_fails_before_spending(tmp_path, capsys, payload):
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    patcher, calls = _patch_client([_GOOD])
    with patcher:
        code = main(_eval_args("--baseline", str(path)))
    assert code == 1
    assert "baseline" in capsys.readouterr().err
    assert calls == []


@pytest.mark.parametrize(
    "raw_score",
    ["NaN", "Infinity", "-Infinity", "1" + "0" * 400],
    ids=["nan", "inf", "neg-inf", "int-overflows-float"],
)
def test_eval_baseline_with_unusable_score_fails_before_spending(
    tmp_path, capsys, raw_score
):
    path = tmp_path / "baseline.json"
    path.write_text(
        '{"models": {"%s": {"format_score_avg": %s}}}' % (_MODEL, raw_score),
        encoding="utf-8",
    )
    patcher, calls = _patch_client([_GOOD])
    with patcher:
        code = main(_eval_args("--baseline", str(path)))
    assert code == 1
    assert "baseline" in capsys.readouterr().err
    assert calls == []


def test_eval_baseline_with_null_scores_is_accepted(tmp_path, capsys):
    path = tmp_path / "baseline.json"
    path.write_text(
        json.dumps({"models": {_MODEL: {"quality_score_avg": None}, "other": {}}}),
        encoding="utf-8",
    )
    patcher, _ = _patch_client([_GOOD])
    with patcher:
        code = main(_eval_args("--baseline", str(path)))
    assert code == 0


def test_eval_missing_key_keeps_other_models_and_writes_report(
    tmp_path, monkeypatch, capsys
):
    from llm_eval import providers

    monkeypatch.delenv(providers.resolve_provider("gemini").api_key_env, raising=False)
    monkeypatch.setenv(providers.resolve_provider("deepseek").api_key_env, "test-key")
    real_factory = providers.create_eval_async_client

    async def _create(**kwargs):
        return _response(_GOOD)

    def _factory(provider):
        real_factory(provider)
        client = MagicMock()
        client.chat.completions.create = _create
        return client

    with patch("llm_eval.runner.create_eval_async_client", side_effect=_factory):
        code = main(
            _eval_args(
                "--output-dir", str(tmp_path), models=f"{_MODEL},deepseek-v4-flash"
            )
        )

    captured = capsys.readouterr()
    assert code == 1
    data = json.loads(captured.out)
    assert data["models"][_MODEL]["errors"] == 2
    assert data["models"]["deepseek-v4-flash"]["errors"] == 0
    report = json.loads(Path(data["report_json"]).read_text(encoding="utf-8"))
    assert set(report["models"]) == {_MODEL, "deepseek-v4-flash"}
    assert f"{_MODEL}: all 2 samples errored" in captured.err


def test_eval_report_git_sha_is_the_package_checkout_not_the_cwd(
    tmp_path, monkeypatch, capsys
):
    expected = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=_LAB_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    elsewhere = tmp_path / "not_a_checkout"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    patcher, _ = _patch_client([_GOOD])
    with patcher:
        code = main(_eval_args("--output-dir", str(tmp_path / "out")))

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    report = json.loads(Path(data["report_json"]).read_text(encoding="utf-8"))
    assert report["git_sha"] == expected


def test_eval_bare_output_dir_writes_to_package_results_from_any_cwd(
    tmp_path, monkeypatch, capsys, package_results_cleanup
):
    """`eval --output-dir` (no value) writes where `review` looks by default."""
    stamp = f"29991231T235959Z-{uuid.uuid4().hex}"
    monkeypatch.setattr("llm_eval.reporting.report_timestamp", lambda: stamp)
    monkeypatch.chdir(tmp_path)
    patcher, _ = _patch_client([_GOOD])
    with patcher:
        code = main([*_eval_args(), "--output-dir"])

    data = json.loads(capsys.readouterr().out)
    report_json = Path(data["report_json"])
    package_results_cleanup.extend([report_json, Path(data["report_markdown"])])
    assert code == 0
    assert report_json.parent == _PACKAGE_RESULTS
    assert report_json.name.startswith(stamp)


def test_eval_reports_unknown_cost_as_na_not_the_provider_price(
    tmp_path, monkeypatch, capsys
):
    """A model the registry no longer prices must show n/a in the table, the
    JSON and the markdown report, not the provider default's price."""
    import dataclasses

    from kg.llm.providers import REGISTRY

    monkeypatch.setitem(
        REGISTRY,
        "gemini",
        dataclasses.replace(REGISTRY["gemini"], chat_model="gemini-next-flash"),
    )
    args = [a for a in _eval_args("--output-dir", str(tmp_path)) if a != "--json"]
    patcher, _ = _patch_client([_GOOD])
    with patcher:
        code = main(args)
    table = capsys.readouterr().out
    with patcher:
        main(_eval_args())
    data = json.loads(capsys.readouterr().out)

    assert code == 0
    row = next(line for line in table.splitlines() if line.startswith(_MODEL))
    assert row.split()[-1] == "n/a"
    assert data["models"][_MODEL]["cost_usd"] is None
    markdown = next(tmp_path.glob("*.md")).read_text(encoding="utf-8")
    md_row = next(line for line in markdown.splitlines() if _MODEL in line)
    assert md_row.rstrip(" |").endswith("n/a")


@pytest.mark.parametrize(
    ("flag", "value"),
    [("--concurrency", "0"), ("--concurrency", "-1"), ("--limit", "0")],
)
def test_eval_rejects_non_positive_counts_before_running(
    flag, value, monkeypatch, capsys
):
    """--concurrency 0 builds Semaphore(0) and hangs forever; --limit 0 is
    falsy and evaluates the whole dataset.  Both are usage errors."""
    calls: list[object] = []

    async def _fake_run_eval(*args, **kwargs):
        calls.append(args)
        return {}

    monkeypatch.setattr("llm_eval.run_eval", _fake_run_eval)
    with pytest.raises(SystemExit) as exc_info:
        main(_eval_args(flag, value))

    assert exc_info.value.code == 2
    assert "must be >= 1" in capsys.readouterr().err
    assert calls == []


def test_corpus_build_shows_help(capsys):
    code = main(["corpus-build"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Build ignored private candidate corpora" in out


def test_gold_queue_shows_help(capsys):
    code = main(["gold-queue"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Sample private candidates" in out
