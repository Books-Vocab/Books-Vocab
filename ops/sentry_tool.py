#!/usr/bin/env -S uv run --python 3.13
"""Headless, read-only Sentry observability CLI for KG agents.

Examples:
  ./ops/sentry_tool.py health --json
  ./ops/sentry_tool.py issues --project ios --environment production --status unresolved --json
  ./ops/sentry_tool.py issue 123 --full --json
  ./ops/sentry_tool.py events --issue 123 --json
  ./ops/sentry_tool.py releases --project ios --json
  ./ops/sentry_tool.py regressions --release 'com.example.app@1.0+2' --json
  ./ops/sentry_tool.py route 123 --json

Every operation is GET-only.  The tool never resolves, assigns, comments on,
creates, or deletes Sentry/GitHub resources.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from sentry_api import SentryAPIClient, SentryAPIError, SentryConfig
from sentry_contract import (
    ERROR_SCHEMA,
    REGRESSIONS_SCHEMA,
    RELEASES_SCHEMA,
    error_payload,
    normalize_event,
    normalize_health,
    normalize_issue,
    normalize_release,
    safe_label,
    safe_opaque_id,
)

EXIT_OK = 0
EXIT_TOOL_ERROR = 1
EXIT_BLOCK = 2
EXIT_WARN = 3
EXIT_USAGE = 64
PROJECT_CHOICES = ("ios", "backend")


class _UsageError(ValueError):
    pass


class _JSONArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _UsageError(message)


def repo_root() -> Path:
    override = os.environ.get("KG_SENTRY_REPO_ROOT")
    return Path(override).expanduser().resolve() if override else Path(__file__).resolve().parents[1]


def load_local_ios_summary(root: Path | None = None) -> dict[str, Any]:
    root = root or repo_root()
    command = ["bash", str(root / "ops/ios_ops.sh"), "sentry", "--json"]
    try:
        result = subprocess.run(
            command,
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            payload = json.loads(result.stdout)
            if isinstance(payload, dict):
                return payload
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        pass
    return {
        "schema": "kg.ios.sentry.v1",
        "verdict": "unchecked",
        "readiness": {},
        "issues": [{"key": "local_summary", "message": "local iOS Sentry summary unavailable"}],
    }


def health(config: SentryConfig, *, root: Path | None = None) -> tuple[dict[str, Any], int]:
    local = load_local_ios_summary(root)
    local_readiness = dict(local.get("readiness") or {})
    api_checks: dict[str, Any] = {
        "api_configured": config.api_configured,
        "api_authenticated": "unchecked",
        "project_reachable": "unchecked",
        "runtime_event_seen": "unchecked",
        "symbolication_ready": "unchecked",
    }
    api_evidence: dict[str, Any] = {"attempted": False}
    if config.api_configured:
        api_evidence["attempted"] = True
        try:
            client = SentryAPIClient(config)
            project_payload = client.project(config.project_ios or "")
            api_checks["api_authenticated"] = True
            api_checks["project_reachable"] = bool(project_payload)
            rows = client.list_issues(
                config.project_ios or "",
                environment="production",
                status="all",
                max_pages=1,
            )
            api_checks["runtime_event_seen"] = bool(rows)
            if rows:
                issue_id = str(rows[0].get("id", ""))
                try:
                    event = client.issue_event(issue_id, "latest", environment="production")
                except SentryAPIError:
                    events = client.list_issue_events(issue_id, environment="production", full=True, max_pages=1)
                    event = events[0] if events else None
                if event:
                    normalized = normalize_issue(
                        rows[0],
                        event=event,
                        project_hint="ios",
                        environment_hint="production",
                    )
                    api_checks["symbolication_ready"] = bool(normalized["evidence"]["stacktrace"])
                    api_evidence["latest_event_id"] = normalized["evidence"]["latest_event_id"]
        except SentryAPIError as error:
            if error.status == 401:
                api_checks["api_authenticated"] = False
                api_checks["project_reachable"] = False
            elif error.status == 403:
                api_checks["api_authenticated"] = True
                api_checks["project_reachable"] = False
            api_evidence["error"] = error.public()
    payload = normalize_health(
        local_readiness=local_readiness,
        project="ios",
        api_checks=api_checks,
    )
    payload["local"] = {
        "verdict": local.get("verdict", "unchecked"),
        "issues": [item.get("key") for item in local.get("issues", []) if isinstance(item, dict) and item.get("key")],
    }
    payload["api"] = api_evidence
    if local.get("verdict") == "blocked":
        payload["verdict"] = "blocked"
    exit_code = {
        "ready": EXIT_OK,
        "blocked": EXIT_BLOCK,
        "partial": EXIT_WARN,
        "unchecked": EXIT_WARN,
    }[payload["verdict"]]
    return payload, exit_code


def command_issues(client: SentryAPIClient, args: argparse.Namespace, config: SentryConfig) -> dict[str, Any]:
    project = _project(config, args.project)
    environment = _environment(args.environment)
    rows = client.list_issues(
        project,
        environment=environment,
        status=args.status,
    )
    return {
        "schema": "kg.sentry.issues.v1",
        "project": project,
        "environment": environment,
        "status": args.status,
        "issues": [
            normalize_issue(row, project_hint=project, environment_hint=environment)
            for row in rows
        ],
        "redaction": {"applied": True, "dropped_fields": []},
    }


def command_issue(client: SentryAPIClient, args: argparse.Namespace, config: SentryConfig) -> dict[str, Any]:
    issue_id = _issue_id(args.issue_id)
    environment = _environment(args.environment)
    raw = client.issue(issue_id, environment=environment)
    event = None
    if args.full:
        try:
            event = client.issue_event(issue_id, "latest", environment=environment)
        except SentryAPIError as error:
            if error.status not in {400, 404}:
                raise
            events = client.list_issue_events(issue_id, environment=environment, full=True, max_pages=1)
            event = events[0] if events else None
    return normalize_issue(
        raw,
        event=event,
        project_hint=_project_hint_for_raw(raw, config),
        environment_hint=environment,
    )


def command_events(client: SentryAPIClient, args: argparse.Namespace, config: SentryConfig) -> dict[str, Any]:
    issue_id = _issue_id(args.issue_id)
    environment = _environment(args.environment)
    events = client.list_issue_events(
        issue_id,
        environment=environment,
        full=True,
    )
    project_hint = "ios" if config.project_ios else None
    return {
        "schema": "kg.sentry.events.v1",
        "issue_id": issue_id,
        "events": [
            normalize_event(
                event,
                issue_id=issue_id,
                project_hint=project_hint,
                environment_hint=environment,
            )
            for event in events
        ],
        "redaction": {"applied": True, "dropped_fields": []},
    }


def command_releases(client: SentryAPIClient, args: argparse.Namespace, config: SentryConfig) -> dict[str, Any]:
    project = _project(config, args.project) if args.project else None
    environment = _environment(args.environment)
    rows = client.releases(project=project, environment=environment)
    return {
        "schema": RELEASES_SCHEMA,
        "project": project,
        "releases": [normalize_release(row, project_hint=project) for row in rows],
        "redaction": {"applied": True, "dropped_fields": []},
    }


def command_regressions(client: SentryAPIClient, args: argparse.Namespace, config: SentryConfig) -> dict[str, Any]:
    project = _project(config, args.project)
    release = _release_arg(args.release)
    rows = client.regressions(project, release)
    return {
        "schema": REGRESSIONS_SCHEMA,
        "project": project,
        "release": release,
        "issues": [normalize_issue(row, project_hint=project) for row in rows],
        "redaction": {"applied": True, "dropped_fields": []},
    }


def command_route(client: SentryAPIClient, args: argparse.Namespace, config: SentryConfig) -> dict[str, Any]:
    issue_args = argparse.Namespace(issue_id=args.issue_id, full=True, environment=None)
    payload = command_issue(client, issue_args, config)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = _JSONArgumentParser(description="Read-only headless Sentry agent tool")
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=_JSONArgumentParser,
    )

    health_parser = subparsers.add_parser("health", help="local wiring plus optional API/runtime readiness")
    _json_flag(health_parser)

    issues_parser = subparsers.add_parser("issues", help="list normalized project issues")
    issues_parser.add_argument("--project", choices=PROJECT_CHOICES, required=True)
    issues_parser.add_argument("--environment", default=None)
    issues_parser.add_argument("--status", choices=("unresolved", "resolved", "all"), default="unresolved")
    _json_flag(issues_parser)

    issue_parser = subparsers.add_parser("issue", help="retrieve one issue")
    issue_parser.add_argument("issue_id")
    issue_parser.add_argument("--environment", default=None)
    issue_parser.add_argument("--full", action="store_true")
    _json_flag(issue_parser)

    events_parser = subparsers.add_parser("events", help="list issue events")
    events_parser.add_argument("--issue", dest="issue_id", required=True)
    events_parser.add_argument("--environment", default=None)
    _json_flag(events_parser)

    releases_parser = subparsers.add_parser("releases", help="list organization releases")
    releases_parser.add_argument("--project", choices=PROJECT_CHOICES, default=None)
    releases_parser.add_argument("--environment", default=None)
    _json_flag(releases_parser)

    regressions_parser = subparsers.add_parser("regressions", help="list unresolved issues for a release")
    regressions_parser.add_argument("--project", choices=PROJECT_CHOICES, default="ios")
    regressions_parser.add_argument("--release", required=True)
    _json_flag(regressions_parser)

    route_parser = subparsers.add_parser("route", help="produce routing recommendation only")
    route_parser.add_argument("issue_id")
    _json_flag(route_parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except _UsageError:
        _emit(error_payload(SentryAPIError("arguments", kind="invalid_usage")))
        return EXIT_USAGE
    config = SentryConfig.from_env()
    try:
        if args.command == "health":
            payload, exit_code = health(config)
        else:
            client = SentryAPIClient(config)
            if args.command == "issues":
                payload, exit_code = command_issues(client, args, config), EXIT_OK
            elif args.command == "issue":
                payload, exit_code = command_issue(client, args, config), EXIT_OK
            elif args.command == "events":
                payload, exit_code = command_events(client, args, config), EXIT_OK
            elif args.command == "releases":
                payload, exit_code = command_releases(client, args, config), EXIT_OK
            elif args.command == "regressions":
                payload, exit_code = command_regressions(client, args, config), EXIT_OK
            elif args.command == "route":
                payload, exit_code = command_route(client, args, config), EXIT_OK
            else:  # pragma: no cover - argparse enforces the choices
                raise SentryAPIError("dispatch", kind="unsupported_command")
    except SentryAPIError as error:
        payload = error_payload(error)
        exit_code = EXIT_WARN if error.kind.startswith("missing_") or error.kind == "network" else EXIT_BLOCK
    except (OSError, ValueError, TypeError) as error:
        payload = {
            "schema": ERROR_SCHEMA,
            "error": {"kind": "tool", "status": None, "retryable": False},
            "redaction": {"applied": True, "dropped_fields": []},
        }
        exit_code = EXIT_TOOL_ERROR
        _ = error
    _emit(payload)
    return exit_code


def _json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="emit stable JSON (default output is also JSON)")


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _project(config: SentryConfig, name: str) -> str:
    value = config.project_for(name)
    safe = safe_label(value, max_length=128) if value else None
    if not value or safe != value:
        raise SentryAPIError("configure", kind=f"missing_project_{name}")
    return safe


def _project_hint_for_raw(raw: dict[str, Any], config: SentryConfig) -> str | None:
    project = raw.get("project")
    slug = project.get("slug") if isinstance(project, dict) else project
    for name in PROJECT_CHOICES:
        if slug and slug == config.project_for(name):
            return name
    return safe_label(slug, max_length=128)


def _safe_release_arg(value: str) -> bool:
    return bool(value and safe_label(value, max_length=256) == value)


def _release_arg(value: str) -> str:
    if not _safe_release_arg(value):
        raise SentryAPIError("arguments", kind="invalid_release")
    return value


def _environment(value: str | None) -> str | None:
    if value is None:
        return None
    safe = safe_label(value, max_length=64)
    if safe != value:
        raise SentryAPIError("arguments", kind="invalid_environment")
    return safe


def _issue_id(value: str) -> str:
    safe = safe_opaque_id(value)
    if safe != value:
        raise SentryAPIError("arguments", kind="invalid_issue_id")
    return safe


if __name__ == "__main__":
    raise SystemExit(main())
