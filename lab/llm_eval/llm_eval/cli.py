"""Unified CLI for KG LLM eval workbench.

Subcommands: eval, prompts, datasets, providers, corpus-build, gold-queue.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


def _emit_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _print_table(headers: list[str], rows: list[list]) -> None:
    if not rows:
        print("(no data)")
        return
    str_rows = [[str(v) for v in row] for row in rows]
    widths = [max(len(h), *(len(r[i]) for r in str_rows)) for i, h in enumerate(headers)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))
    for row in str_rows:
        print(fmt.format(*row))


# -- subcommand handlers --


def cmd_eval(args: argparse.Namespace) -> int:
    from llm_eval import EvalConfig, PromptRegistry, make_render_fn, run_eval
    from llm_eval.datasets import load_dataset
    from llm_eval.reporting import (
        compare_to_baseline,
        current_git_sha,
        report_timestamp,
        write_report,
    )

    registry = PromptRegistry()
    prompt_name = args.prompt
    version = args.version

    try:
        meta = registry.get_meta(prompt_name, version)
    except KeyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        dataset = load_dataset(args.dataset)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not dataset:
        print("Error: dataset is empty", file=sys.stderr)
        return 1

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if not models:
        print("Error: no models specified", file=sys.stderr)
        return 1

    config = EvalConfig(
        prompt_name=prompt_name,
        prompt_version=meta.version,
        dataset_name=args.dataset,
        limit=args.limit,
        concurrency=args.concurrency,
        temperature=args.temperature,
    )

    render_fn = make_render_fn(registry, prompt_name, version)
    fallback_prompt = render_fn(dataset[0])

    summaries = asyncio.run(
        run_eval(fallback_prompt, dataset, models, config, render_fn)
    )

    result: dict[str, Any] = {
        "prompt": prompt_name,
        "version": meta.version,
        "dataset": args.dataset,
        "models": {},
    }
    for model, summary in summaries.items():
        result["models"][model] = {
            "provider": summary.provider,
            "samples": summary.sample_count,
            "errors": summary.error_count,
            "format_score": summary.format_score_avg,
            "quality_score": summary.quality_score_avg,
            "avg_latency_ms": round(summary.avg_latency_ms),
            "cost_usd": round(summary.total_cost_usd, 6),
            "score_breakdown": summary.score_breakdown,
        }

    if args.output_dir:
        dataset_bytes = json.dumps(dataset, sort_keys=True).encode()
        dataset_hash = hashlib.sha256(dataset_bytes).hexdigest()[:12]
        paths = write_report(
            summaries=summaries,
            output_dir=Path(args.output_dir),
            prompt_name=prompt_name,
            prompt_version=meta.version,
            dataset_name=args.dataset,
            dataset_hash=dataset_hash,
            config=dataclasses.asdict(config),
            git_sha=current_git_sha(),
            timestamp=report_timestamp(),
        )
        result["report_json"] = str(paths.json_path)
        result["report_markdown"] = str(paths.markdown_path)

    if args.baseline:
        baseline_path = Path(args.baseline)
        if not baseline_path.exists():
            print(f"Warning: baseline not found: {baseline_path}", file=sys.stderr)
        else:
            baseline_data = json.loads(baseline_path.read_text(encoding="utf-8"))
            deltas = compare_to_baseline(summaries, baseline_data)
            result["baseline_comparison"] = deltas

    if args.json:
        _emit_json(result)
    else:
        print(f"Prompt: {prompt_name}@{meta.version}  Dataset: {args.dataset}")
        print()
        rows = []
        for model, info in result["models"].items():
            rows.append([
                model,
                info["provider"],
                str(info["samples"]),
                str(info["errors"]),
                _fmt_score(info["format_score"]),
                _fmt_score(info["quality_score"]),
                str(info["avg_latency_ms"]),
                f"${info['cost_usd']:.6f}",
            ])
        _print_table(
            ["model", "provider", "samples", "errors", "format", "quality", "latency_ms", "cost"],
            rows,
        )
        if "baseline_comparison" in result:
            print()
            print("Baseline comparison:")
            for model, delta in result["baseline_comparison"].items():
                parts = []
                if delta.get("format_delta") is not None:
                    parts.append(f"format {delta['format_delta']:+.3f}")
                if delta.get("quality_delta") is not None:
                    parts.append(f"quality {delta['quality_delta']:+.3f}")
                regression = " ⚠ REGRESSION" if delta.get("format_regression") or delta.get("quality_regression") else ""
                print(f"  {model}: {', '.join(parts) or 'n/a'}{regression}")
        if "report_json" in result:
            print()
            print(f"Report: {result['report_json']}")

    return 0


def cmd_prompts(args: argparse.Namespace) -> int:
    from llm_eval.registry import PromptRegistry

    registry = PromptRegistry()

    if args.name:
        try:
            meta = registry.get_meta(args.name)
        except KeyError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        info = {
            "name": meta.name,
            "version": meta.version,
            "file": meta.file,
            "source_of_truth": meta.source_of_truth,
            "tags": meta.tags,
            "schema": meta.schema,
        }
        if args.json:
            _emit_json(info)
        else:
            for key, val in info.items():
                if isinstance(val, (list, dict)):
                    val = json.dumps(val, ensure_ascii=False)
                print(f"{key:20s}  {val}")
        return 0

    prompts = registry.list_prompts()
    if args.json:
        items = []
        for name in prompts:
            versions = registry.list_versions(name)
            meta = registry.get_meta(name)
            items.append({
                "name": name,
                "versions": versions,
                "tags": meta.tags,
            })
        _emit_json(items)
    else:
        rows = []
        for name in prompts:
            versions = registry.list_versions(name)
            meta = registry.get_meta(name)
            rows.append([name, ", ".join(versions), ", ".join(meta.tags)])
        _print_table(["name", "versions", "tags"], rows)

    return 0


def cmd_datasets(args: argparse.Namespace) -> int:
    from llm_eval.datasets import list_datasets, load_dataset

    if args.name:
        try:
            samples = load_dataset(args.name)
        except FileNotFoundError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        has_gold = any(s.get("gold_status") == "human_gold" for s in samples)
        preview = samples[:3]
        info = {
            "name": args.name,
            "rows": len(samples),
            "has_gold": has_gold,
            "preview": preview,
        }
        if args.json:
            _emit_json(info)
        else:
            print(f"Dataset: {args.name}  Rows: {len(samples)}  Gold: {has_gold}")
            print()
            for i, sample in enumerate(preview):
                print(f"--- sample {i} ---")
                print(json.dumps(sample, ensure_ascii=False, indent=2))
        return 0

    names = sorted(list_datasets())
    if args.json:
        items = []
        for name in names:
            samples = load_dataset(name)
            has_gold = any(s.get("gold_status") == "human_gold" for s in samples)
            items.append({"name": name, "rows": len(samples), "has_gold": has_gold})
        _emit_json(items)
    else:
        rows = []
        for name in names:
            samples = load_dataset(name)
            has_gold = any(s.get("gold_status") == "human_gold" for s in samples)
            rows.append([name, str(len(samples)), "yes" if has_gold else "no"])
        _print_table(["name", "rows", "gold"], rows)

    return 0


def cmd_providers(args: argparse.Namespace) -> int:
    from llm_eval.providers import list_available_providers

    providers = list_available_providers()
    if args.json:
        items = []
        for p in providers:
            items.append({
                "name": p.name,
                "chat_model": p.chat_model,
                "input_price_per_m": p.input_price_per_m,
                "output_price_per_m": p.output_price_per_m,
                "key_configured": bool(os.getenv(p.api_key_env)) if p.name != "ollama" else True,
            })
        _emit_json(items)
    else:
        rows = []
        for p in providers:
            key_ok = "yes" if (p.name == "ollama" or os.getenv(p.api_key_env)) else "no"
            rows.append([
                p.name,
                p.chat_model,
                f"${p.input_price_per_m:.2f}",
                f"${p.output_price_per_m:.2f}",
                key_ok,
            ])
        _print_table(["name", "chat_model", "in_$/M", "out_$/M", "key"], rows)

    return 0


def _fmt_score(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


# -- main --


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if argv and argv[0] == "corpus-build":
        from llm_eval.corpus_cli import main as corpus_main
        return corpus_main(argv[1:] or ["--help"])

    if argv and argv[0] == "gold-queue":
        from llm_eval.gold_queue_cli import main as gq_main
        return gq_main(argv[1:] or ["--help"])

    parser = argparse.ArgumentParser(
        prog="llm-eval",
        description="KG LLM eval workbench CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Delegated subcommands (own --help):\n"
               "  corpus-build    Build private candidate corpora from user dump\n"
               "  gold-queue      Sample candidates into human gold review queue\n",
    )
    sub = parser.add_subparsers(dest="command")

    jp = argparse.ArgumentParser(add_help=False)
    jp.add_argument("--json", action="store_true", help="JSON output")

    # eval
    p_eval = sub.add_parser("eval", parents=[jp], help="Run LLM evaluation")
    p_eval.add_argument("--prompt", required=True, help="Prompt name (e.g. translate_quick)")
    p_eval.add_argument("--dataset", required=True, help="Dataset name (e.g. translate_quick_gold)")
    p_eval.add_argument("--models", required=True, help="Comma-separated model list")
    p_eval.add_argument("--version", default=None, help="Prompt version (default: latest)")
    p_eval.add_argument("--limit", type=int, default=None, help="Max samples to evaluate")
    p_eval.add_argument("--concurrency", type=int, default=5, help="Per-provider concurrency")
    p_eval.add_argument("--temperature", type=float, default=0.3, help="LLM temperature")
    p_eval.add_argument("--output-dir", default=None, help="Write report to directory")
    p_eval.add_argument("--baseline", default=None, help="Path to baseline JSON for comparison")
    p_eval.set_defaults(func=cmd_eval)

    # prompts
    p_prompts = sub.add_parser("prompts", parents=[jp], help="List / show prompt metadata")
    p_prompts.add_argument("--name", default=None, help="Show detail for a specific prompt")
    p_prompts.set_defaults(func=cmd_prompts)

    # datasets
    p_datasets = sub.add_parser("datasets", parents=[jp], help="List / preview datasets")
    p_datasets.add_argument("--name", default=None, help="Show detail for a specific dataset")
    p_datasets.set_defaults(func=cmd_datasets)

    # providers
    p_providers = sub.add_parser("providers", parents=[jp], help="List available LLM providers")
    p_providers.set_defaults(func=cmd_providers)

    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
