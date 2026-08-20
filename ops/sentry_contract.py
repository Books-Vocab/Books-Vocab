#!/usr/bin/env -S uv run --python 3.13
"""Versioned, privacy-first Sentry payload contracts for KG agents."""

from __future__ import annotations

import ipaddress
import re
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

HEALTH_SCHEMA = "kg.sentry.health.v1"
ISSUE_SCHEMA = "kg.sentry.issue.v1"
EVENT_SCHEMA = "kg.sentry.event.v1"
RELEASES_SCHEMA = "kg.sentry.releases.v1"
REGRESSIONS_SCHEMA = "kg.sentry.regressions.v1"
ERROR_SCHEMA = "kg.sentry.error.v1"

VERDICTS = {"ready", "partial", "blocked", "unchecked"}
_ID = re.compile(r"^[A-Za-z0-9._:/+@-]{1,256}$")
_SPACED_ID = re.compile(r"^[A-Za-z0-9._:/+@ -]{1,256}$")
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[A-Za-z]{2,63}\b")
_SAFE_EVENT_MESSAGE = re.compile(r"^[a-z0-9][a-z0-9._/-]*(?: [a-z0-9][a-z0-9._/-]*){0,7}$")
_HTTP_MESSAGE = re.compile(r"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(.+)$")
_SAFE_API_ROOTS = {
    "auth",
    "books",
    "billing",
    "decks",
    "dictionary",
    "graph",
    "health",
    "library",
    "notebooks",
    "pipeline",
    "podcasts",
    "system",
    "translate",
    "user",
    "vocab",
}
_SENSITIVE_TEXT = re.compile(
    r"(?:authorization|cookie|password|secret|token|email|input|user|book|card|translation|query|body|content)\s*[:=]",
    re.IGNORECASE,
)
_SAFE_BREADCRUMB_KEYS = {
    "attempt",
    "duration_ms",
    "error_type",
    "feature",
    "format",
    "method",
    "operation",
    "phase",
    "provider",
    "request_id",
    "result",
    "retry_count",
    "status_code",
    "url",
    "url_error_code",
}
_SAFE_LEVELS = {"debug", "info", "warning", "error", "fatal"}
_SAFE_STATUS = {"unresolved", "resolved", "ignored", "reprocessing", "unknown"}


class _Redaction:
    def __init__(self) -> None:
        self.dropped: set[str] = set()

    def drop(self, field: str) -> None:
        safe_field = field if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", field) else "redacted_field"
        self.dropped.add(safe_field)

    def result(self) -> dict[str, Any]:
        return {"applied": True, "dropped_fields": sorted(self.dropped)}


def strip_query(value: str) -> str:
    return value.split("?", 1)[0].strip()


def safe_opaque_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if _OPAQUE_ID.fullmatch(value) else None


def safe_label(value: Any, *, max_length: int = 256, allow_spaces: bool = False) -> str | None:
    if not isinstance(value, str):
        return None
    value = strip_query(value).strip()
    if not value or len(value) > max_length or _EMAIL.search(value) or _SENSITIVE_TEXT.search(value):
        return None
    try:
        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        return None
    pattern = _SPACED_ID if allow_spaces else _ID
    return value if pattern.fullmatch(value) else None


def safe_message(value: Any, *, max_length: int = 200) -> str | None:
    """Keep only fixed diagnostic labels or canonical API resource roots."""
    if not isinstance(value, str):
        return None
    value = strip_query(value).replace("\n", " ").strip()
    if not value or len(value) > max_length or _EMAIL.search(value) or _SENSITIVE_TEXT.search(value):
        return None
    http_match = _HTTP_MESSAGE.fullmatch(value)
    if http_match:
        endpoint = safe_endpoint(http_match.group(2))
        if endpoint:
            return f"{http_match.group(1)} {endpoint}"
        return None
    # Product breadcrumbs use short, source-controlled labels. Reject prose,
    # punctuation and content-shaped words so an exception/book title cannot
    # cross this boundary merely because it is short.
    if _SAFE_EVENT_MESSAGE.fullmatch(value) and not set(value.split()) & {
        "book",
        "card",
        "content",
        "input",
        "text",
        "title",
        "translation",
        "user",
    }:
        return value
    return None


def safe_endpoint(value: Any) -> str | None:
    """Reduce a URL/path to an allowlisted API resource root, never an ID."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw or any(character.isspace() for character in raw):
        return None
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    path = unquote(parsed.path if parsed.scheme or parsed.netloc else raw.split("?", 1)[0].split("#", 1)[0])
    components = [component for component in path.split("/") if component]
    if len(components) < 2 or components[0].lower() != "api":
        return None
    root = components[1].lower()
    if root not in _SAFE_API_ROOTS:
        return None
    return f"/api/{root}"


def normalize_issue(
    raw: dict[str, Any],
    *,
    event: dict[str, Any] | None = None,
    project_hint: str | None = None,
    environment_hint: str | None = None,
) -> dict[str, Any]:
    redaction = _Redaction()
    event = event or {}
    issue_id = safe_opaque_id(raw.get("id")) or safe_opaque_id(raw.get("groupID")) or "unknown"
    short_id = safe_label(raw.get("shortId"), max_length=128) or issue_id
    project = _project_slug(raw, project_hint, redaction)
    platform = _platform(raw, event, redaction)
    environments = _environments(raw, event, environment_hint, redaction)
    release = _release(raw, event, redaction)
    dist = safe_label(raw.get("dist"), max_length=128)
    status = raw.get("status") if raw.get("status") in _SAFE_STATUS else "unknown"
    if status == "unknown" and raw.get("status") is not None:
        redaction.drop("issue.status")
    level = raw.get("level") if raw.get("level") in _SAFE_LEVELS else "error"
    if raw.get("level") is not None and level == "error" and raw.get("level") not in _SAFE_LEVELS:
        redaction.drop("issue.level")
    exception_type = _exception_type(event, redaction)
    title = _safe_issue_title(raw, exception_type, redaction)
    stacktrace = _stacktrace(event, redaction)
    breadcrumbs = _breadcrumbs(event, redaction)
    request_ids = _request_ids(raw, event, breadcrumbs, redaction)
    evidence = {
        "latest_event_id": safe_opaque_id(event.get("eventID") or event.get("event_id") or event.get("id")),
        "exception_type": exception_type,
        "stacktrace": stacktrace,
        "breadcrumbs": breadcrumbs,
        "request_ids": request_ids,
        "device": _device_context(event, "device", redaction),
        "os": _device_context(event, "os", redaction),
    }
    routing = route_for_issue(
        project=project,
        platform=platform,
        release=release,
        request_ids=request_ids,
        stacktrace=stacktrace,
        status=status,
    )
    return {
        "schema": ISSUE_SCHEMA,
        "issue": {
            "id": issue_id,
            "short_id": short_id,
            "title": title,
            "status": status,
            "level": level,
            "project": project,
            "platform": platform,
            "environment": environments,
            "release": release,
            "dist": dist,
            "count": _non_negative_int(raw.get("count"), redaction, "issue.count"),
            "user_count": _non_negative_int(raw.get("userCount"), redaction, "issue.user_count"),
            "first_seen": _safe_timestamp(raw.get("firstSeen"), redaction, "issue.first_seen"),
            "last_seen": _safe_timestamp(raw.get("lastSeen"), redaction, "issue.last_seen"),
        },
        "evidence": evidence,
        "routing": routing,
        "redaction": redaction.result(),
    }


def normalize_event(
    raw: dict[str, Any],
    *,
    issue_id: str | None = None,
    project_hint: str | None = None,
    environment_hint: str | None = None,
) -> dict[str, Any]:
    issue = normalize_issue(
        {"id": issue_id or raw.get("groupID") or raw.get("issueID"), "project": project_hint},
        event=raw,
        project_hint=project_hint,
        environment_hint=environment_hint,
    )
    return {
        "schema": EVENT_SCHEMA,
        "event": {
            "id": issue["evidence"]["latest_event_id"] or "unknown",
            "issue_id": safe_opaque_id(issue_id) if issue_id else None,
            "created_at": _safe_timestamp(raw.get("dateCreated") or raw.get("timestamp"), _Redaction(), "event.created_at"),
        },
        "evidence": issue["evidence"],
        "redaction": issue["redaction"],
    }


def normalize_release(raw: dict[str, Any], *, project_hint: str | None = None) -> dict[str, Any]:
    redaction = _Redaction()
    projects: list[str] = []
    for project in raw.get("projects") or []:
        if isinstance(project, dict):
            project_slug = safe_label(project.get("slug"), max_length=128)
        else:
            project_slug = safe_label(project, max_length=128)
        if project_slug:
            projects.append(project_slug)
        elif project is not None:
            redaction.drop("release.projects")
    safe_project_hint = safe_label(project_hint, max_length=128)
    if safe_project_hint and safe_project_hint not in projects:
        projects.insert(0, safe_project_hint)
    elif project_hint is not None and safe_project_hint is None:
        redaction.drop("release.projects")
    return {
        "version": safe_label(raw.get("version"), max_length=256),
        "short_version": safe_label(raw.get("shortVersion"), max_length=256),
        "status": safe_label(raw.get("status"), max_length=32),
        "date_created": _safe_timestamp(raw.get("dateCreated"), redaction, "release.date_created"),
        "date_released": _safe_timestamp(raw.get("dateReleased"), redaction, "release.date_released"),
        "first_event": _safe_timestamp(raw.get("firstEvent"), redaction, "release.first_event"),
        "last_event": _safe_timestamp(raw.get("lastEvent"), redaction, "release.last_event"),
        "new_groups": _non_negative_int(raw.get("newGroups"), redaction, "release.new_groups"),
        "projects": projects,
        "redaction": redaction.result(),
    }


def normalize_health(
    *,
    local_readiness: dict[str, Any] | None,
    project: str | None,
    api_checks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    local = local_readiness or {}
    checks = {
        key: local.get(key, "unchecked")
        for key in (
            "source_present",
            "package_present",
            "target_linked",
            "build_can_import",
            "api_configured",
            "api_authenticated",
            "project_reachable",
            "runtime_event_seen",
            "symbolication_ready",
        )
    }
    if api_checks:
        checks.update({key: value for key, value in api_checks.items() if key in checks})
    static_keys = ("source_present", "package_present", "target_linked")
    if any(value is False for value in (checks[key] for key in static_keys)):
        verdict = "blocked"
    elif all(checks[key] is True for key in checks):
        verdict = "ready"
    elif any(value != "unchecked" for value in checks.values()):
        verdict = "partial"
    else:
        verdict = "unchecked"
    return {
        "schema": HEALTH_SCHEMA,
        "verdict": verdict,
        "project": safe_label(project, max_length=128),
        "checks": checks,
        "redaction": {"applied": True, "dropped_fields": []},
    }


def route_for_issue(
    *,
    project: str | None,
    platform: str | None,
    release: str | None,
    request_ids: list[str],
    stacktrace: list[dict[str, Any]],
    status: str,
) -> dict[str, Any]:
    is_ios = project == "ios" or platform in {"swift", "cocoa", "apple"}
    if is_ios:
        surface, worker, reason = "ios", "ios-worker", "project/platform"
    elif project == "backend":
        surface, worker, reason = "backend", "backend-worker", "project/platform"
    else:
        surface, worker, reason = "unknown", "unassigned", "project/platform unavailable"
    evidence_incomplete = not stacktrace or not release
    suggestions: list[dict[str, Any]] = [
        {"worker": worker, "reason": reason},
    ]
    if status == "unresolved" and release:
        suggestions.append({"worker": worker, "reason": "unresolved release evidence; prioritize regression check"})
    if request_ids:
        suggestions.append({"worker": "backend-correlation-worker", "reason": "request_id correlation evidence present"})
    if evidence_incomplete:
        suggestions.append({"worker": "evidence-collector", "reason": "evidence_incomplete; do not guess root cause"})
    return {
        "surface": surface,
        "worker": worker,
        "reason": reason,
        "evidence_incomplete": evidence_incomplete,
        "suggestions": suggestions,
        "write_policy": "read-only recommendation; IM owns issue/PR/assign/resolve writes",
        "dedupe_policy": "defer-to-im-existing-issue-pr",
    }


def error_payload(error: Exception) -> dict[str, Any]:
    public = error.public() if hasattr(error, "public") else {"kind": "tool", "status": None, "retryable": False}
    return {"schema": ERROR_SCHEMA, "error": public, "redaction": {"applied": True, "dropped_fields": []}}


def _project_slug(raw: dict[str, Any], hint: str | None, redaction: _Redaction) -> str | None:
    project = raw.get("project")
    if isinstance(project, dict):
        project = project.get("slug") or project.get("name")
    result = safe_label(project, max_length=128) or safe_label(hint, max_length=128)
    if project is not None and result is None:
        redaction.drop("issue.project")
    return result


def _platform(raw: dict[str, Any], event: dict[str, Any], redaction: _Redaction) -> str | None:
    value = raw.get("platform")
    if not value and isinstance(raw.get("project"), dict):
        value = raw["project"].get("platform")
    value = value or event.get("platform")
    result = safe_label(value, max_length=64)
    if value is not None and result is None:
        redaction.drop("issue.platform")
    return result.lower() if result else None


def _environments(
    raw: dict[str, Any], event: dict[str, Any], hint: str | None, redaction: _Redaction
) -> list[str]:
    values: list[Any] = []
    raw_value = raw.get("environment")
    if isinstance(raw_value, list):
        values.extend(raw_value)
    elif raw_value:
        values.append(raw_value)
    if hint:
        values.append(hint)
    for key, value in _tags(event).items():
        if key == "environment":
            values.append(value)
    result: list[str] = []
    for value in values:
        safe = safe_label(value, max_length=64)
        if safe and safe not in result:
            result.append(safe)
        elif value is not None:
            redaction.drop("issue.environment")
    return result


def _release(raw: dict[str, Any], event: dict[str, Any], redaction: _Redaction) -> str | None:
    value = raw.get("release")
    if isinstance(value, dict):
        value = value.get("version")
    value = value or _tags(event).get("release")
    result = safe_label(value, max_length=256)
    if value is not None and result is None:
        redaction.drop("issue.release")
    return result


def _exception_type(event: dict[str, Any], redaction: _Redaction) -> str | None:
    values = _exception_values(event)
    value = values[-1].get("type") if values else None
    result = _safe_exception_type(value)
    if value is not None and result is None:
        redaction.drop("exception.type")
    return result


def _safe_issue_title(raw: dict[str, Any], exception_type: str | None, redaction: _Redaction) -> str:
    value = raw.get("title") or (raw.get("metadata") or {}).get("title")
    if not isinstance(value, str):
        return exception_type or "unknown"
    value = strip_query(value).strip()
    prefix = value.split(":", 1)[0].strip()
    if _looks_like_type(prefix) or prefix.startswith(("HTTP ", "GET ", "POST ", "PUT ", "DELETE ")):
        safe = safe_message(prefix) or _safe_exception_type(prefix)
        if safe:
            return safe
    redaction.drop("issue.title")
    return exception_type or "redacted"


def _stacktrace(event: dict[str, Any], redaction: _Redaction) -> list[dict[str, Any]]:
    values = _exception_values(event)
    if not values:
        return []
    stacktrace = values[-1].get("stacktrace") or {}
    frames = stacktrace.get("frames") if isinstance(stacktrace, dict) else None
    if not isinstance(frames, list):
        return []
    result: list[dict[str, Any]] = []
    for index, frame in enumerate(reversed(frames[-50:])):
        if not isinstance(frame, dict):
            redaction.drop("evidence.stacktrace")
            continue
        filename = frame.get("filename") or frame.get("absPath") or frame.get("function")
        if isinstance(filename, str):
            basename = PurePosixPath(filename.split("?", 1)[0]).name or None
            filename = safe_label(basename, max_length=256)
        function = safe_label(frame.get("function"), max_length=160)
        module = safe_label(frame.get("module") or frame.get("package"), max_length=160)
        row: dict[str, Any] = {"index": index}
        if filename:
            row["filename"] = filename
        if function:
            row["function"] = function
        if module:
            row["module"] = module
        line = _int_or_none(frame.get("lineNo") or frame.get("lineNumber"))
        column = _int_or_none(frame.get("colNo") or frame.get("column"))
        if line is not None:
            row["line"] = line
        if column is not None:
            row["column"] = column
        if isinstance(frame.get("inApp"), bool):
            row["in_app"] = frame["inApp"]
        if len(row) > 1:
            result.append(row)
    return result


def _breadcrumbs(event: dict[str, Any], redaction: _Redaction) -> list[dict[str, Any]]:
    values: Any = (event.get("breadcrumbs") or {}).get("values") if isinstance(event.get("breadcrumbs"), dict) else None
    if values is None:
        for entry in event.get("entries") or []:
            if isinstance(entry, dict) and entry.get("type") == "breadcrumbs":
                values = (entry.get("data") or {}).get("values")
                break
    if not isinstance(values, list):
        return []
    result: list[dict[str, Any]] = []
    for crumb in values[-20:]:
        if not isinstance(crumb, dict):
            continue
        row: dict[str, Any] = {}
        category = safe_label(crumb.get("category"), max_length=80)
        level = crumb.get("level") if crumb.get("level") in _SAFE_LEVELS else None
        message = safe_message(crumb.get("message"))
        if category:
            row["category"] = category
        if level:
            row["level"] = level
        if message:
            row["message"] = message
        data = _breadcrumb_data(crumb.get("data"), redaction)
        if data:
            row["data"] = data
        timestamp = _safe_timestamp(crumb.get("timestamp"), redaction, "breadcrumb.timestamp")
        if timestamp:
            row["timestamp"] = timestamp
        if row:
            result.append(row)
    return result


def _breadcrumb_data(value: Any, redaction: _Redaction) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key, raw in value.items():
        normalized = str(key).lower()
        if normalized not in _SAFE_BREADCRUMB_KEYS:
            redaction.drop(f"breadcrumb.data.{normalized}")
            continue
        if normalized == "request_id":
            safe = safe_opaque_id(raw)
        elif normalized == "url":
            safe = safe_endpoint(raw)
        elif isinstance(raw, bool) or isinstance(raw, (int, float)) and not isinstance(raw, bool):
            safe = raw
        else:
            safe = safe_label(raw, max_length=160)
        if safe is not None:
            result[normalized] = safe
        else:
            redaction.drop(f"breadcrumb.data.{normalized}")
    return result


def _request_ids(
    raw: dict[str, Any], event: dict[str, Any], breadcrumbs: list[dict[str, Any]], redaction: _Redaction
) -> list[str]:
    values: list[Any] = []
    tags = _tags(event)
    for key in ("request_id", "request.id", "request-id"):
        if key in tags:
            values.append(tags[key])
    for crumb in breadcrumbs:
        data = crumb.get("data") or {}
        if "request_id" in data:
            values.append(data["request_id"])
    if raw.get("request_id"):
        values.append(raw["request_id"])
    result: list[str] = []
    for value in values:
        safe = safe_opaque_id(value)
        if safe and safe not in result:
            result.append(safe)
        elif value is not None:
            redaction.drop("evidence.request_ids")
    return result[:20]


def _device_context(event: dict[str, Any], name: str, redaction: _Redaction) -> dict[str, str]:
    contexts = event.get("contexts") if isinstance(event.get("contexts"), dict) else {}
    value = contexts.get(name) or event.get(name)
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key in ("name", "model", "family", "brand", "version", "build"):
        safe = safe_label(value.get(key), max_length=128, allow_spaces=True)
        if safe:
            result[key] = safe
        elif value.get(key) is not None:
            redaction.drop(f"evidence.{name}.{key}")
    return result


def _tags(event: dict[str, Any]) -> dict[str, Any]:
    tags = event.get("tags")
    if isinstance(tags, dict):
        return {str(key).lower(): value for key, value in tags.items()}
    if isinstance(tags, list):
        result: dict[str, Any] = {}
        for item in tags:
            if isinstance(item, dict) and item.get("key") is not None:
                result[str(item["key"]).lower()] = item.get("value")
        return result
    return {}


def _exception_values(event: dict[str, Any]) -> list[dict[str, Any]]:
    direct = event.get("exception")
    if isinstance(direct, dict) and isinstance(direct.get("values"), list):
        return [item for item in direct["values"] if isinstance(item, dict)]
    for entry in event.get("entries") or []:
        if isinstance(entry, dict) and entry.get("type") == "exception":
            values = (entry.get("data") or {}).get("values")
            if isinstance(values, list):
                return [item for item in values if isinstance(item, dict)]
    values = event.get("exceptionValues")
    return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []


def _looks_like_type(value: str) -> bool:
    return bool(re.fullmatch(r"(?:[A-Za-z_$][A-Za-z0-9_$.]*)(?:Error|Exception|Failure|Crash|Fault)?", value)) and (
        value.endswith(("Error", "Exception", "Failure", "Crash", "Fault")) or value in {"Crash", "Exception"}
    )


def _safe_exception_type(value: Any) -> str | None:
    safe = safe_label(value, max_length=160)
    return safe if safe and _looks_like_type(safe) else None


def _safe_timestamp(value: Any, redaction: _Redaction, field: str) -> str | None:
    if value is None:
        return None
    safe = safe_label(value, max_length=64)
    if safe and ("T" in safe or safe.isdigit()):
        return safe
    redaction.drop(field)
    return None


def _non_negative_int(value: Any, redaction: _Redaction, field: str) -> int:
    number = _int_or_none(value)
    if number is None or number < 0:
        if value is not None:
            redaction.drop(field)
        return 0
    return number


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


__all__ = [
    "ERROR_SCHEMA",
    "EVENT_SCHEMA",
    "HEALTH_SCHEMA",
    "ISSUE_SCHEMA",
    "REGRESSIONS_SCHEMA",
    "RELEASES_SCHEMA",
    "normalize_event",
    "normalize_health",
    "normalize_issue",
    "normalize_release",
    "route_for_issue",
    "safe_endpoint",
    "safe_label",
    "safe_message",
    "safe_opaque_id",
    "strip_query",
]
