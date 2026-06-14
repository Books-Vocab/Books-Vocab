"""Report persistence and baseline comparison for eval runs."""

from __future__ import annotations

import dataclasses
import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .runner import EvalResult, EvalSummary


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReportPaths:
    json_path: Path
    markdown_path: Path


def current_git_sha(cwd: Path | None = None) -> str:
    """Return the current git sha, or ``unknown`` outside a git checkout."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd) if cwd else None,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        LOGGER.warning("Failed to read git sha; using unknown", exc_info=True)
        return "unknown"


def report_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def write_report(
    *,
    summaries: dict[str, EvalSummary],
    output_dir: Path,
    prompt_name: str,
    prompt_version: str,
    dataset_name: str,
    dataset_hash: str,
    config: dict[str, Any],
    git_sha: str | None = None,
    timestamp: str | None = None,
) -> ReportPaths:
    """Write JSON + Markdown reports for one eval run."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = timestamp or report_timestamp()
    sha = git_sha or current_git_sha()
    base = f"{ts}_{_slug(prompt_name)}_{_slug(dataset_name)}"
    json_path = output_dir / f"{base}.json"
    markdown_path = output_dir / f"{base}.md"
    payload = {
        "timestamp": ts,
        "git_sha": sha,
        "prompt": {"name": prompt_name, "version": prompt_version},
        "dataset_name": dataset_name,
        "dataset_hash": dataset_hash,
        "config": config,
        "models": {
            model: _summary_to_dict(summary)
            for model, summary in summaries.items()
        },
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_markdown(payload), encoding="utf-8")
    return ReportPaths(json_path=json_path, markdown_path=markdown_path)


def compare_to_baseline(
    current: dict[str, EvalSummary],
    baseline: dict[str, Any],
    *,
    epsilon: float = 1e-9,
) -> dict[str, dict[str, Any]]:
    """Compare current summaries to a prior report/baseline payload."""
    previous_models = baseline.get("models", {})
    result: dict[str, dict[str, Any]] = {}
    for model, summary in current.items():
        previous = previous_models.get(model, {})
        format_delta = _delta(summary.format_score_avg, previous.get("format_score_avg"))
        quality_delta = _delta(summary.quality_score_avg, previous.get("quality_score_avg"))
        result[model] = {
            "format_delta": format_delta,
            "quality_delta": quality_delta,
            "format_regression": format_delta is not None and format_delta < -epsilon,
            "quality_regression": quality_delta is not None and quality_delta < -epsilon,
        }
    return result


def _summary_to_dict(summary: EvalSummary) -> dict[str, Any]:
    payload = dataclasses.asdict(summary)
    payload["samples"] = [_result_to_dict(sample) for sample in summary.samples]
    return payload


def _result_to_dict(result: EvalResult) -> dict[str, Any]:
    return dataclasses.asdict(result)


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# LLM Eval Report: {payload['prompt']['name']}",
        "",
        f"- prompt: `{payload['prompt']['name']}@{payload['prompt']['version']}`",
        f"- dataset: `{payload['dataset_name']}` (`{payload['dataset_hash']}`)",
        f"- git: `{payload['git_sha']}`",
        "",
        "| model | provider | samples | errors | format | quality | latency_ms | cost_usd |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model, summary in payload["models"].items():
        lines.append(
            f"| `{model}` | {summary['provider']} | {summary['sample_count']} | "
            f"{summary['error_count']} | {_fmt_score(summary.get('format_score_avg'))} | "
            f"{_fmt_score(summary.get('quality_score_avg'))} | "
            f"{summary['avg_latency_ms']:.0f} | {summary['total_cost_usd']:.6f} |"
        )
    return "\n".join(lines) + "\n"


def _fmt_score(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value).strip("_")


def _delta(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return round(float(current) - float(previous), 10)
