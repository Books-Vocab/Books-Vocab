#!/usr/bin/env -S uv run --python 3.13
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass


SCHEMA = "kg.capability_matrix.v1"


@dataclass(frozen=True)
class Tier:
    key: str
    rank: int
    summary: str


@dataclass(frozen=True)
class Surface:
    key: str
    entrypoint: str
    command: str
    minimumTier: str
    sideEffect: str
    scope: str
    purpose: str


TIERS = [
    Tier("observer", 1, "唯讀觀測；不可觸發本機或生產寫入"),
    Tier("operator", 2, "可執行本機操作與低風險 orchestration；仍不可做生產寫入"),
    Tier("editor", 3, "可做有 guard 的內容/資料編輯；需明確 commit gate"),
    Tier("production-capable", 4, "可執行 deploy、migration、production write、raw escape hatch"),
]


SURFACES = [
    Surface("branch.audit", "./ops/branch_audit.sh", "./ops/branch_audit.sh --json", "observer", "repo-read", "repo", "遠端分支 reachability audit"),
    Surface("review.audit", "./ops/review_audit.sh", "./ops/review_audit.sh --json", "observer", "repo-read", "repo", "review receipt contract audit"),
    Surface("capability.matrix", "./ops/capability_matrix.py", "./ops/capability_matrix.py --json", "observer", "repo-read", "repo", "查詢 agent capability contract"),
    Surface("docs.impact", "./ops/docs_impact.py", "./ops/docs_impact.py --since <base> --json", "observer", "repo-read", "repo", "docs registry impact candidates for changed files"),
    Surface("docs.lint.gate", "./ops/docs_lint.sh", "./ops/docs_lint.sh", "observer", "repo-read", "repo", "daily docs registry and changed-docs gate"),
    Surface("docs.registry.coverage", "./ops/docs_registry_coverage.py", "./ops/docs_registry_coverage.py --json", "observer", "repo-read", "repo", "docs registry coverage audit"),
    Surface("release.status", "./ops/release.sh", "./ops/release.sh status", "observer", "repo-read", "repo", "api/iOS release status and suggested version bump"),
    Surface("release.changelog", "./ops/release.sh", "./ops/release.sh changelog <api|ios>", "observer", "repo-read", "repo", "release changelog preview"),
    Surface("release.bump", "./ops/release.sh", "./ops/release.sh bump <api|ios> <x.y.z>", "editor", "repo-write", "repo", "local version-file bump"),
    Surface("release.publish", "./ops/release.sh", "./ops/release.sh publish <api|ios> <x.y.z> --yes", "production-capable", "repo-write external-push", "external", "commit version files, tag, and push release marker"),
    Surface("devops.safe.status", "./ops/devops_kg_safe.sh", "./ops/devops_kg_safe.sh status", "observer", "prod-read", "production", "production app/container status"),
    Surface("devops.safe.health", "./ops/devops_kg_safe.sh", "./ops/devops_kg_safe.sh health --json", "observer", "prod-read", "production", "host-level health aggregation"),
    Surface("devops.safe.logs", "./ops/devops_kg_safe.sh", "./ops/devops_kg_safe.sh logs 80", "observer", "prod-read", "production", "production log tail"),
    Surface("devops.safe.caddy-status", "./ops/devops_kg_safe.sh", "./ops/devops_kg_safe.sh caddy-status", "observer", "prod-read", "production", "Caddy service status"),
    Surface("devops.safe.docker-ps", "./ops/devops_kg_safe.sh", "./ops/devops_kg_safe.sh docker-ps", "observer", "prod-read", "production", "container inventory"),
    Surface("devops.safe.ops_cli", "./ops/devops_kg_safe.sh", "./ops/devops_kg_safe.sh ops-cli <subcommand>", "observer", "prod-read", "production", "container-side readonly business queries"),
    Surface("ios.ops.readonly", "./ops/ios_ops.sh", "./ops/ios_ops.sh commands --json", "observer", "local-read", "local", "self-describing iOS ops readonly catalog"),
    Surface("ios.ops.build", "./ops/ios_ops.sh", "./ops/ios_ops.sh build --json", "operator", "local-build", "local", "local compile gate"),
    Surface("ios.ops.test", "./ops/ios_ops.sh", "./ops/ios_ops.sh test --json", "operator", "local-test", "local", "local verification run"),
    Surface("ios.ops.catalog", "./ops/ios_ops.sh", "./ops/ios_ops.sh catalog snapshots --json", "operator", "local-artifact", "local", "local screenshot artifact generation"),
    Surface("capture.profile.run", "./ops/capture_profile.py", "./ops/capture_profile.py run --profile <file>", "operator", "local-artifact", "local", "marketing capture orchestration"),
    Surface("podcast.ops.status", "./ops/podcast_ops.py", "./ops/podcast_ops.py status --json", "observer", "local-read", "local", "headless podcast workspace status"),
    Surface("podcast.ops.episodes", "./ops/podcast_ops.py", "./ops/podcast_ops.py episodes <workspace> --json", "observer", "local-read", "local", "podcast per-episode gate matrix"),
    Surface("podcast.ops.reconcile", "./ops/podcast_ops.py", "./ops/podcast_ops.py reconcile --json", "observer", "external-read", "external", "podcast disk-to-S3 publish drift check"),
    Surface("llm_eval.cli", "lab/llm_eval", "(cd lab/llm_eval && uv run python scripts/cli.py <subcommand>)", "operator", "local-test", "local", "LLM prompt evaluation and corpus/gold-queue workbench"),
    Surface("devops.safe.ops_edit", "./ops/devops_kg_safe.sh", "./ops/devops_kg_safe.sh ops-edit <subcommand> --commit", "production-capable", "prod-write", "production", "guarded production data mutation"),
    Surface("devops.safe.deploy", "./ops/devops_kg_safe.sh", "./ops/devops_kg_safe.sh deploy", "production-capable", "prod-write deploy", "production", "deploy code to production"),
    Surface("devops.safe.migrate", "./ops/devops_kg_safe.sh", "./ops/devops_kg_safe.sh migrate", "production-capable", "prod-write migration", "production", "run production migration"),
    Surface("devops.safe.restart", "./ops/devops_kg_safe.sh", "./ops/devops_kg_safe.sh restart", "production-capable", "prod-write restart", "production", "restart production service"),
    Surface("devops.safe.run-exception", "./ops/devops_kg_safe.sh", "./ops/devops_kg_safe.sh run \"<cmd>\"", "production-capable", "prod-escape-hatch", "production", "exception path for raw remote commands"),
    Surface("devops.safe.container-run-exception", "./ops/devops_kg_safe.sh", "./ops/devops_kg_safe.sh container-run \"<cmd>\"", "production-capable", "prod-escape-hatch", "production", "exception path for raw container commands"),
    Surface("ios.ops.archive-upload", "./ops/ios_ops.sh", "./ops/ios_ops.sh archive --upload --json", "production-capable", "external-upload local-build", "external", "archive/export/upload build artifact"),
]


def build_payload(tier_filter: str | None) -> dict:
    tier_map = {tier.key: asdict(tier) for tier in TIERS}
    surfaces = [asdict(surface) for surface in SURFACES if tier_filter in (None, surface.minimumTier)]
    return {
        "schema": SCHEMA,
        "filter": {"tier": tier_filter},
        "tiers": list(tier_map.values()),
        "summary": {
            "tiers": len(TIERS),
            "surfaces": len(surfaces),
            "productionWriteSurfaces": sum("prod-write" in s["sideEffect"] for s in surfaces),
            "readOnlySurfaces": sum(s["sideEffect"] in {"repo-read", "prod-read", "local-read"} for s in surfaces),
        },
        "surfaces": surfaces,
    }


def format_text(payload: dict) -> str:
    lines: list[str] = []
    for tier in payload["tiers"]:
        lines.append(f"[capability][tier] {tier['key']} rank={tier['rank']} summary={tier['summary']}")
    for surface in payload["surfaces"]:
        lines.append(
            "[capability][surface] "
            f"{surface['key']} minimumTier={surface['minimumTier']} sideEffect={surface['sideEffect']} "
            f"scope={surface['scope']} command=\"{surface['command']}\""
        )
    return "\n".join(lines) + ("\n" if lines else "")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="emit machine-readable agent capability tiers for key KG control-plane surfaces")
    parser.add_argument("--json", action="store_true", help="output JSON payload")
    parser.add_argument("--tier", choices=[tier.key for tier in TIERS], help="filter surfaces by minimum tier")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    payload = build_payload(args.tier)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_text(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
