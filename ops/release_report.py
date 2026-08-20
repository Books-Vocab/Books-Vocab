#!/usr/bin/env -S uv run --with pyjwt --with cryptography python
"""Read-only release provenance and cross-surface version-diff report.

The report deliberately keeps three authorities separate:

* Git refs/tags identify source snapshots and their tree hashes.
* App Store Connect identifies the iOS binary and channel state.
* ``/api/system/info`` identifies the backend process currently serving.

It never infers a source commit from a local app, archive timestamp, or a
matching marketing version.  An iOS build without ``ios/<version>+<build>``
is reported as unbound instead of being guessed into a release.

Exit codes:
  0 complete report (aligned or drift observed)
  2 report generated but one or more required anchors are unavailable/bound
  64 invalid command line
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA = "kg.release.report.v1"
DIFF_SCHEMA = "kg.release.diff.v1"
DEFAULT_APP_ID = os.environ.get("ASC_APP_ID", "6759816274")
DEFAULT_BACKEND_URL = os.environ.get("KG_BACKEND_URL", "https://wordnexus.lol")
IOS_PROJECT_FILE = "ios/BooksAndVocab.xcodeproj/project.pbxproj"
BACKEND_VERSION_FILE = "backend/pyproject.toml"
SURFACE_PATHS = {"ios": ("ios",), "backend": ("backend",)}


class ReportError(RuntimeError):
    """A fail-closed report input or normalization error."""


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _unavailable(reason: str, *, status: str = "unavailable") -> dict[str, str]:
    return {"status": status, "reason": reason}


def _version_key(version: str) -> tuple[int, tuple[Any, ...]]:
    match = re.fullmatch(r"\d+(?:\.\d+)*", version.strip())
    if match:
        return (1, tuple(int(part) for part in version.split(".")))
    return (0, (version,))


def _is_http_error(payload: Mapping[str, Any]) -> bool:
    return "_httpError" in payload


def parse_ios_settings(text: str) -> dict[str, str]:
    """Parse one consistent iOS marketing/build tuple from a pbxproj."""

    values: dict[str, str] = {}
    for name in ("MARKETING_VERSION", "CURRENT_PROJECT_VERSION"):
        matches = {
            value.strip().strip('"')
            for value in re.findall(
                rf"^\s*{re.escape(name)}\s*=\s*([^;]+);", text, flags=re.MULTILINE
            )
        }
        if not matches:
            raise ReportError(f"iOS project is missing {name}")
        if len(matches) != 1:
            rendered = ", ".join(sorted(matches))
            raise ReportError(f"iOS project has conflicting {name}: {rendered}")
        values[name] = next(iter(matches))
    return {
        "marketingVersion": values["MARKETING_VERSION"],
        "build": values["CURRENT_PROJECT_VERSION"],
    }


def parse_backend_version(text: str) -> str | None:
    match = re.search(r"^\s*version\s*=\s*[\"']([^\"']+)[\"']", text, flags=re.MULTILINE)
    return match.group(1) if match else None


def _pre_release_attributes(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    included = payload.get("included")
    if not isinstance(included, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in included:
        if not isinstance(item, dict) or item.get("type") != "preReleaseVersions":
            continue
        item_id = item.get("id")
        attrs = item.get("attributes")
        if isinstance(item_id, str) and isinstance(attrs, dict):
            result[item_id] = attrs
    return result


def normalize_asc_builds(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return only iOS TestFlight builds with a resolvable pre-release version."""

    if _is_http_error(payload):
        raise ReportError(f"ASC builds lookup failed: HTTP {payload.get('_httpError')}")
    data = payload.get("data")
    if not isinstance(data, list):
        raise ReportError("ASC builds response has no data list")
    prereleases = _pre_release_attributes(payload)
    builds: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict) or item.get("type") != "builds":
            continue
        attrs = item.get("attributes")
        relationship = item.get("relationships")
        if not isinstance(attrs, dict) or not isinstance(relationship, dict):
            continue
        linkage = relationship.get("preReleaseVersion", {}).get("data")
        if not isinstance(linkage, dict):
            continue
        prerelease = prereleases.get(str(linkage.get("id")))
        if not isinstance(prerelease, dict) or prerelease.get("platform") != "IOS":
            continue
        build_number = attrs.get("version")
        version = prerelease.get("version")
        build_id = item.get("id")
        if not isinstance(build_number, str) or not build_number:
            raise ReportError("ASC iOS build has invalid build number")
        if not isinstance(version, str) or not version:
            raise ReportError("ASC iOS build has invalid marketing version")
        if not isinstance(build_id, str) or not build_id:
            raise ReportError("ASC iOS build has no stable id")
        normalized: dict[str, Any] = {
            "status": "observed",
            "version": version,
            "build": build_number,
            "ascBuildId": build_id,
            "processingState": attrs.get("processingState", "UNKNOWN"),
        }
        if isinstance(attrs.get("uploadedDate"), str):
            normalized["uploadedAt"] = attrs["uploadedDate"]
        for source, target in (
            ("minOsVersion", "minOsVersion"),
            ("usesNonExemptEncryption", "usesNonExemptEncryption"),
            ("buildAudienceType", "buildAudienceType"),
        ):
            if source in attrs:
                normalized[target] = attrs[source]
        builds.append(normalized)
    builds.sort(
        key=lambda item: (str(item.get("uploadedAt", "")), str(item["ascBuildId"])),
        reverse=True,
    )
    return builds


def normalize_asc_versions(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return iOS App Store versions, preserving their channel state."""

    if _is_http_error(payload):
        raise ReportError(
            f"ASC App Store versions lookup failed: HTTP {payload.get('_httpError')}"
        )
    data = payload.get("data")
    if not isinstance(data, list):
        raise ReportError("ASC App Store versions response has no data list")
    versions: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict) or item.get("type") != "appStoreVersions":
            continue
        attrs = item.get("attributes")
        if not isinstance(attrs, dict):
            continue
        platform = attrs.get("platform")
        if platform is not None and platform != "IOS":
            continue
        version = attrs.get("versionString")
        state = attrs.get("appStoreState")
        version_id = item.get("id")
        if not isinstance(version, str) or not version:
            raise ReportError("ASC App Store version has invalid versionString")
        if not isinstance(state, str) or not state:
            raise ReportError("ASC App Store version has invalid appStoreState")
        if not isinstance(version_id, str) or not version_id:
            raise ReportError("ASC App Store version has no stable id")
        normalized: dict[str, Any] = {
            "status": "observed",
            "version": version,
            "state": state,
            "ascVersionId": version_id,
        }
        for source, target in (("createdDate", "createdAt"), ("releaseDate", "releasedAt")):
            if isinstance(attrs.get(source), str):
                normalized[target] = attrs[source]
        versions.append(normalized)
    versions.sort(
        key=lambda item: (_version_key(str(item["version"])), str(item.get("createdAt", ""))),
        reverse=True,
    )
    return versions


def normalize_asc_snapshot(
    builds_payload: Mapping[str, Any], versions_payload: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    builds = normalize_asc_builds(builds_payload)
    versions = normalize_asc_versions(versions_payload)
    testflight = builds[0] if builds else _unavailable("ASC returned no iOS TestFlight builds")
    ready = [item for item in versions if item.get("state") == "READY_FOR_SALE"]
    app_store_candidates = ready or versions
    app_store = (
        app_store_candidates[0]
        if app_store_candidates
        else _unavailable("ASC returned no iOS App Store versions")
    )
    return {"testflight": dict(testflight), "appStore": dict(app_store)}


def fetch_asc_snapshot(app_id: str = DEFAULT_APP_ID) -> dict[str, dict[str, Any]]:
    """Read current ASC channel evidence through the existing JWT GET helper."""

    ops_dir = Path(__file__).resolve().parent
    if str(ops_dir) not in sys.path:
        sys.path.insert(0, str(ops_dir))
    try:
        from asc_get import get, mint_token  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - environment-specific
        raise ReportError(f"ASC GET helper unavailable: {exc}") from exc

    token = mint_token()
    builds_query = urllib.parse.urlencode(
        {
            "filter[app]": app_id,
            "include": "preReleaseVersion",
            "sort": "-uploadedDate",
            "limit": "50",
        }
    )
    versions_query = urllib.parse.urlencode(
        {"filter[platform]": "IOS", "limit": "200"}
    )
    return normalize_asc_snapshot(
        get(f"/v1/builds?{builds_query}", token),
        get(f"/v1/apps/{urllib.parse.quote(app_id, safe='')}/appStoreVersions?{versions_query}", token),
    )


def fetch_backend_live(base_url: str = DEFAULT_BACKEND_URL) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/api/system/info"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "kg-release-report/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ReportError(f"backend live probe failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReportError("backend live probe returned a non-object JSON payload")
    version = payload.get("version")
    if not isinstance(version, str) or not version:
        raise ReportError("backend live probe has no version")
    result: dict[str, Any] = {
        "status": "observed",
        "url": url,
        "version": version,
    }
    for source, target in (
        ("started_at", "startedAt"),
        ("uptime_seconds", "uptimeSeconds"),
        ("migration_version", "migrationVersion"),
        ("sentry", "sentry"),
    ):
        if source in payload:
            result[target] = payload[source]
    return result


class Git:
    def __init__(self, repo: Path):
        self.repo = repo.resolve()

    def run(self, args: Sequence[str], *, allow_failure: bool = False) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            if allow_failure:
                return ""
            detail = result.stderr.strip() or result.stdout.strip()
            command = "git " + " ".join(args)
            raise ReportError(f"{command} failed: {detail}")
        return result.stdout.strip()

    def resolve(self, ref: str) -> str:
        resolved = self.run(["rev-parse", "--verify", f"{ref}^{{commit}}"])
        if not re.fullmatch(r"[0-9a-f]{40}", resolved):
            raise ReportError(f"ref {ref} did not resolve to a full commit")
        return resolved

    def tree(self, sha: str) -> str:
        tree = self.run(["rev-parse", f"{sha}^{{tree}}"])
        if not re.fullmatch(r"[0-9a-f]{40}", tree):
            raise ReportError(f"commit {sha} did not resolve to a full tree")
        return tree

    def show(self, sha: str, path: str) -> str:
        return self.run(["show", f"{sha}:{path}"])


def _identity(git: Git, ref: str) -> dict[str, Any]:
    try:
        sha = git.resolve(ref)
        return {"status": "observed", "ref": ref, "sha": sha, "tree": git.tree(sha)}
    except ReportError as exc:
        return {"status": "unavailable", "ref": ref, "reason": str(exc)}


def _bind_tag(git: Git, tag: str) -> dict[str, Any]:
    try:
        sha = git.resolve(tag)
        return {
            "status": "bound",
            "tag": tag,
            "sha": sha,
            "tree": git.tree(sha),
        }
    except ReportError:
        return {
            "status": "unbound",
            "tag": tag,
            "reason": "source binding tag is absent or does not name a commit",
        }


def _parse_numstat(text: str) -> tuple[int, int, list[dict[str, str]]]:
    insertions = 0
    deletions = 0
    files: list[dict[str, str]] = []
    for line in text.splitlines():
        fields = line.split("\t", 2)
        if len(fields) != 3:
            continue
        added, removed, path = fields
        if added.isdigit():
            insertions += int(added)
        if removed.isdigit():
            deletions += int(removed)
        files.append({"status": "M", "path": path})
    return insertions, deletions, files


def _parse_name_status(text: str) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) >= 2:
            files.append({"status": fields[0], "path": fields[-1]})
    return files


def _blocked_diff(surface: str, from_ref: str, to_ref: str, reason: str) -> dict[str, Any]:
    return {
        "schema": DIFF_SCHEMA,
        "status": "blocked",
        "surface": surface,
        "from": {"ref": from_ref},
        "to": {"ref": to_ref},
        "reason": reason,
    }


def diff_refs(repo: str | Path, surface: str, from_ref: str, to_ref: str) -> dict[str, Any]:
    """Compare two source anchors for one product surface."""

    if surface not in SURFACE_PATHS:
        raise ReportError(f"unsupported diff surface: {surface}")
    git = Git(Path(repo))
    from_identity = _identity(git, from_ref)
    to_identity = _identity(git, to_ref)
    if from_identity.get("status") != "observed":
        return _blocked_diff(surface, from_ref, to_ref, f"from ref unavailable: {from_ref}")
    if to_identity.get("status") != "observed":
        return _blocked_diff(surface, from_ref, to_ref, f"to ref unavailable: {to_ref}")
    paths = SURFACE_PATHS[surface]
    range_ref = f"{from_identity['sha']}..{to_identity['sha']}"
    numstat = git.run(["diff", "--numstat", "--no-renames", range_ref, "--", *paths])
    insertions, deletions, numstat_files = _parse_numstat(numstat)
    name_status = git.run(["diff", "--name-status", "--no-renames", range_ref, "--", *paths])
    files = _parse_name_status(name_status)
    if not files:
        files = numstat_files
    log_text = git.run(
        ["log", "--no-merges", "--format=%H%x09%s", range_ref, "--", *paths]
    )
    commits = []
    for line in log_text.splitlines():
        sha, separator, subject = line.partition("\t")
        if separator:
            commits.append({"sha": sha, "subject": subject})
    result: dict[str, Any] = {
        "schema": DIFF_SCHEMA,
        "status": "changed" if files else "identical",
        "surface": surface,
        "from": from_identity,
        "to": to_identity,
        "changedFiles": len(files),
        "insertions": insertions,
        "deletions": deletions,
        "commitCount": len(commits),
        "commits": commits,
        "files": files,
    }
    return result


def _enrich_ref(git: Git, identity: dict[str, Any]) -> dict[str, Any]:
    result = dict(identity)
    if identity.get("status") != "observed":
        return result
    sha = str(identity["sha"])
    try:
        result["iosProject"] = parse_ios_settings(git.show(sha, IOS_PROJECT_FILE))
    except ReportError as exc:
        result["iosProject"] = _unavailable(str(exc))
    try:
        result["backendVersion"] = parse_backend_version(git.show(sha, BACKEND_VERSION_FILE))
    except ReportError:
        result["backendVersion"] = None
    return result


def _artifact_identity(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {"status": "not_provided"}
    artifact = Path(path).expanduser().resolve()
    if not artifact.is_file():
        return {"status": "blocked", "path": str(artifact), "reason": "artifact is missing"}
    digest = hashlib.sha256()
    size = 0
    with artifact.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return {
        "status": "observed",
        "path": str(artifact),
        "bytes": size,
        "sha256": digest.hexdigest(),
    }


def _live_alignment(git: Git, production: Mapping[str, Any], live: Mapping[str, Any]) -> str:
    if production.get("status") != "observed" or live.get("status") != "observed":
        return "unknown"
    prod_sha = str(production["sha"])
    live_version = str(live.get("version", ""))
    if prod_sha.startswith(live_version) or live_version == prod_sha:
        return "aligned"
    try:
        live_sha = git.resolve(live_version)
    except ReportError:
        return "unknown"
    if live_sha == prod_sha:
        return "aligned"
    try:
        if git.tree(live_sha) == production.get("tree"):
            return "same-tree-different-commit"
    except ReportError:
        pass
    return "drift"


def _source_binding(git: Git, version: Any, build: Any | None = None) -> dict[str, Any]:
    if not isinstance(version, str) or not version:
        return {"status": "blocked", "reason": "missing marketing version"}
    if build is None:
        return _bind_tag(git, f"ios/{version}")
    if not isinstance(build, str) or not build:
        return {"status": "blocked", "reason": "missing TestFlight build number"}
    return _bind_tag(git, f"ios/{version}+{build}")


def _same_tuple(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return left.get("status") == "observed" and right.get("status") == "observed" and (
        left.get("version"),
        left.get("build"),
    ) == (right.get("version"), right.get("build"))


def build_report(
    repo: str | Path,
    *,
    main_ref: str = "origin/main",
    production_ref: str = "origin/prod",
    asc_snapshot: Mapping[str, Any] | None = None,
    backend_live: Mapping[str, Any] | None = None,
    app_id: str = DEFAULT_APP_ID,
    backend_url: str = DEFAULT_BACKEND_URL,
    fetch_external: bool = True,
    generated_at: str | None = None,
    ipa_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build one deterministic report from Git plus explicit external evidence."""

    root = Path(repo).resolve()
    git = Git(root)
    main = _enrich_ref(git, _identity(git, main_ref))
    production = _enrich_ref(git, _identity(git, production_ref))

    asc: Mapping[str, Any]
    if asc_snapshot is None and fetch_external:
        try:
            asc = fetch_asc_snapshot(app_id)
        except (ReportError, OSError, ValueError, TypeError, KeyError) as exc:
            # External boundary: preserve the partial report and fail closed.
            asc = {
                "testflight": _unavailable(f"ASC evidence unavailable: {exc}"),
                "appStore": _unavailable(f"ASC evidence unavailable: {exc}"),
            }
    else:
        asc = asc_snapshot or {
            "testflight": _unavailable("ASC evidence not requested"),
            "appStore": _unavailable("ASC evidence not requested"),
        }

    if backend_live is None and fetch_external:
        try:
            live: Mapping[str, Any] = fetch_backend_live(backend_url)
        except (ReportError, OSError, ValueError, TypeError, KeyError) as exc:
            # External boundary: preserve the partial report and fail closed.
            live = _unavailable(f"backend live evidence unavailable: {exc}")
    else:
        live = backend_live or _unavailable("backend live evidence not requested")

    testflight = dict(asc.get("testflight", _unavailable("TestFlight evidence missing")))
    app_store = dict(asc.get("appStore", _unavailable("App Store evidence missing")))
    testflight["sourceBinding"] = _source_binding(
        git, testflight.get("version"), testflight.get("build")
    )
    app_store["sourceBinding"] = _source_binding(git, app_store.get("version"))

    if testflight["sourceBinding"].get("status") == "bound" and main.get("status") == "observed":
        testflight_to_main = diff_refs(
            root, "ios", str(testflight["sourceBinding"]["sha"]), str(main["sha"])
        )
    else:
        testflight_to_main = _blocked_diff(
            "ios",
            str(testflight.get("sourceBinding", {}).get("tag", "TestFlight")),
            main_ref,
            "TestFlight source binding or main ref is unavailable",
        )

    if (
        app_store["sourceBinding"].get("status") == "bound"
        and testflight["sourceBinding"].get("status") == "bound"
    ):
        app_store_to_testflight = diff_refs(
            root,
            "ios",
            str(app_store["sourceBinding"]["sha"]),
            str(testflight["sourceBinding"]["sha"]),
        )
    else:
        app_store_to_testflight = _blocked_diff(
            "ios",
            str(app_store.get("sourceBinding", {}).get("tag", "App Store")),
            str(testflight.get("sourceBinding", {}).get("tag", "TestFlight")),
            "App Store or TestFlight source binding is unavailable",
        )

    if main.get("status") == "observed" and production.get("status") == "observed":
        production_to_main = diff_refs(root, "backend", str(production["sha"]), str(main["sha"]))
    else:
        production_to_main = _blocked_diff(
            "backend", production_ref, main_ref, "production or main ref is unavailable"
        )
    production = dict(production)
    production["live"] = dict(live)
    production["liveAlignment"] = _live_alignment(git, production, live)

    ios = {
        "main": main,
        "testflight": testflight,
        "appStore": app_store,
        "testflightToMain": testflight_to_main,
        "appStoreToTestFlight": app_store_to_testflight,
        "artifact": _artifact_identity(ipa_path),
    }
    backend = {
        "main": main,
        "production": production,
        "productionToMain": production_to_main,
    }

    blockers: list[str] = []
    reasons: list[str] = []
    for label, evidence in (("TestFlight", testflight), ("App Store", app_store)):
        if evidence.get("status") != "observed":
            blockers.append(f"{label} channel evidence unavailable")
        elif evidence.get("sourceBinding", {}).get("status") != "bound":
            blockers.append(f"{label} binary has no immutable Git source binding")
    if main.get("status") != "observed":
        blockers.append(f"main ref unavailable: {main_ref}")
    if production.get("status") != "observed":
        blockers.append(f"production ref unavailable: {production_ref}")
    if live.get("status") != "observed":
        blockers.append("backend live evidence unavailable")

    if testflight_to_main.get("status") == "changed":
        reasons.append(
            f"main contains {testflight_to_main['changedFiles']} iOS files and "
            f"{testflight_to_main['commitCount']} commits after the latest TestFlight source"
        )
    if (
        app_store.get("status") == "observed"
        and testflight.get("status") == "observed"
        and (app_store.get("version"), app_store.get("build"))
        != (testflight.get("version"), testflight.get("build"))
    ):
        reasons.append(
            f"App Store {app_store.get('version')} and TestFlight "
            f"{testflight.get('version')} build {testflight.get('build')} are different channel tuples"
        )
    if app_store_to_testflight.get("status") == "changed":
        reasons.append(
            f"TestFlight source differs from the App Store source by "
            f"{app_store_to_testflight['changedFiles']} iOS files"
        )
    if production_to_main.get("status") == "changed":
        reasons.append(
            f"main contains {production_to_main['changedFiles']} backend files and "
            f"{production_to_main['commitCount']} commits after production"
        )
    if production.get("liveAlignment") == "same-tree-different-commit":
        reasons.append("backend live SHA differs from origin/prod, but both resolve to the same tree")
    elif production.get("liveAlignment") == "drift":
        reasons.append("backend live SHA/tree does not match origin/prod")

    status = "blocked" if blockers else ("drift" if reasons else "aligned")
    headline = {
        "blocked": "不能把目前狀態視為完整可追溯：有 release anchor 缺失",
        "drift": "目前 channel/runtime 與 main 並非同一個 release snapshot",
        "aligned": "目前 channel/runtime 與 main 的可驗證 release snapshot 一致",
    }[status]
    return {
        "schema": SCHEMA,
        "generatedAt": generated_at or _utc_now(),
        "repository": {
            "root": str(root),
            "mainRef": main_ref,
            "main": main,
            "productionRef": production_ref,
            "production": production,
        },
        "ios": ios,
        "backend": backend,
        "verdict": {
            "status": status,
            "headline": headline,
            "blockers": blockers,
            "reasons": reasons,
        },
    }


def _format_delta(label: str, delta: Mapping[str, Any]) -> str:
    status = str(delta.get("status", "unknown")).upper()
    if status == "BLOCKED":
        return f"{label}: BLOCKED — {delta.get('reason', 'missing evidence')}"
    return (
        f"{label}: {status} — files={delta.get('changedFiles', 0)}, "
        f"commits={delta.get('commitCount', 0)}, +{delta.get('insertions', 0)}/-{delta.get('deletions', 0)}"
    )


def render_report(report: Mapping[str, Any]) -> str:
    """Render the machine report as a short executive briefing."""

    verdict = report.get("verdict", {})
    status = str(verdict.get("status", "unknown")).upper()
    ios = report.get("ios", {})
    backend = report.get("backend", {})
    testflight = ios.get("testflight", {})
    app_store = ios.get("appStore", {})
    production = backend.get("production", {})
    live = production.get("live", {}) if isinstance(production, dict) else {}
    lines = [
        f"[KG release-report] verdict={status}",
        f"結論：{verdict.get('headline', '無法判定')}",
        "",
        "iOS",
        f"- App Store：{app_store.get('version', 'unknown')} ({app_store.get('state', 'unknown')})",
        f"- TestFlight {testflight.get('version', 'unknown')} (build {testflight.get('build', 'unknown')})",
        f"- TestFlight source：{testflight.get('sourceBinding', {}).get('status', 'unknown')}",
        _format_delta("- TestFlight → main", ios.get("testflightToMain", {})),
        _format_delta("- App Store → TestFlight", ios.get("appStoreToTestFlight", {})),
        "",
        "Backend",
        f"- production ref：{production.get('sha', 'unknown')}",
        f"- live：{live.get('version', 'unknown')} ({production.get('liveAlignment', 'unknown')})",
        _format_delta("- production → main", backend.get("productionToMain", {})),
    ]
    blockers = verdict.get("blockers", [])
    reasons = verdict.get("reasons", [])
    if blockers:
        lines.extend(["", "Blockers:", *[f"- {item}" for item in blockers]])
    if reasons:
        lines.extend(["", "原因:", *[f"- {item}" for item in reasons]])
    return "\n".join(lines)


def _load_json(path: str | Path) -> Any:
    try:
        return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportError(f"cannot read JSON fixture {path}: {exc}") from exc


def _load_asc_fixture(path: str | None) -> Mapping[str, Any] | None:
    if path is None:
        return None
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise ReportError("ASC fixture must be a JSON object")
    if "testflight" in payload and "appStore" in payload:
        return payload
    builds = payload.get("builds")
    versions = payload.get("appStoreVersions", payload.get("versions"))
    if not isinstance(builds, dict) or not isinstance(versions, dict):
        raise ReportError("ASC fixture needs testflight/appStore or builds/appStoreVersions")
    return normalize_asc_snapshot(builds, versions)


def _load_backend_fixture(path: str | None) -> Mapping[str, Any] | None:
    if path is None:
        return None
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise ReportError("backend fixture must be a JSON object")
    if "status" in payload:
        return payload
    version = payload.get("version")
    if not isinstance(version, str) or not version:
        raise ReportError("backend fixture has no version")
    return {"status": "observed", "version": version, **payload}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="唯讀報告 Git source、iOS ASC channel 與 backend live/prod/main 差異"
    )
    parser.add_argument("command", nargs="?", choices=("snapshot", "diff"), default="snapshot")
    parser.add_argument("--repo", default=".", help="Git repository root")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--main-ref", default="origin/main")
    parser.add_argument("--prod-ref", default="origin/prod")
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument("--app-id", default=DEFAULT_APP_ID)
    parser.add_argument("--asc-fixture", help="offline ASC JSON fixture")
    parser.add_argument("--backend-fixture", help="offline /api/system/info JSON fixture")
    parser.add_argument("--skip-external", action="store_true", help="do not query ASC or live backend")
    parser.add_argument("--ipa", help="optional local IPA; report its SHA-256 without claiming ASC equality")
    parser.add_argument("--from", dest="from_ref", help="diff source ref")
    parser.add_argument("--to", dest="to_ref", help="diff target ref")
    parser.add_argument("--surface", choices=("ios", "backend"), default="ios")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "diff":
            if not args.from_ref or not args.to_ref:
                print("diff 需要 --from <ref> 與 --to <ref>", file=sys.stderr)
                return 64
            result = diff_refs(args.repo, args.surface, args.from_ref, args.to_ref)
            print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else _format_delta(args.surface, result))
            return 0 if result.get("status") != "blocked" else 2

        asc_fixture = _load_asc_fixture(args.asc_fixture)
        backend_fixture = _load_backend_fixture(args.backend_fixture)
        report = build_report(
            args.repo,
            main_ref=args.main_ref,
            production_ref=args.prod_ref,
            asc_snapshot=asc_fixture,
            backend_live=backend_fixture,
            app_id=args.app_id,
            backend_url=args.backend_url,
            fetch_external=not args.skip_external,
            ipa_path=args.ipa,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render_report(report))
        return 0 if report["verdict"]["status"] != "blocked" else 2
    except (ReportError, OSError, ValueError, TypeError) as exc:
        print(f"release_report: BLOCKED — {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
