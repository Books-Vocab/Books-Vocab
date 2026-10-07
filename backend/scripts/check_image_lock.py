"""Assert that a built backend image installs exactly the versions in uv.lock (#2088).

CI tests the locked dependency tree, so an image that resolves its dependencies
at build time ships versions nobody tested and cannot be rebuilt reproducibly
for a rollback. This check reads the image's installed distributions
(``importlib.metadata``) and its PEP 508 marker environment, walks ``uv.lock``
from the root project for that environment, and reports:

- missing:    a locked runtime dependency that is not installed;
- mismatched: an installed distribution whose version differs from uv.lock;
- unexpected: an installed distribution that uv.lock does not account for;
- duplicated: a distribution installed more than once.

Dependency groups are never required. ``--allow-group`` lets the image carry
packages from a group (the admin test matrix runs pytest in the container), but
they must still be at the locked versions.

Usage (from backend/):
    uv run --locked python scripts/check_image_lock.py --image <tag> --allow-group dev

Exit status: 0 = image matches uv.lock, 1 = drift found, 2 = usage, lock or probe error.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packaging.markers import Marker
from packaging.version import InvalidVersion, Version

DEFAULT_LOCK = Path(__file__).resolve().parent.parent / "uv.lock"

# python:3.13-slim ships pip as its only distribution. It is the base image's
# installer, not an application dependency, so uv.lock does not account for it.
BASE_IMAGE_DISTRIBUTIONS = frozenset({"pip"})

# Runs inside the image with the stdlib only. The environment mirrors
# packaging.markers.default_environment(), so markers are evaluated for the
# image (Linux, its CPU architecture) rather than for the machine running the check.
PROBE = r"""
import importlib.metadata, json, os, platform, sys

def _version(info):
    version = "{0.major}.{0.minor}.{0.micro}".format(info)
    if info.releaselevel != "final":
        version += info.releaselevel[0] + str(info.serial)
    return version

environment = {
    "implementation_name": sys.implementation.name,
    "implementation_version": _version(sys.implementation.version),
    "os_name": os.name,
    "platform_machine": platform.machine(),
    "platform_release": platform.release(),
    "platform_system": platform.system(),
    "platform_version": platform.version(),
    "python_full_version": platform.python_version(),
    "platform_python_implementation": platform.python_implementation(),
    "python_version": ".".join(platform.python_version_tuple()[:2]),
    "sys_platform": sys.platform,
}
distributions = [
    [dist.metadata["Name"] or "", dist.version or ""]
    for dist in importlib.metadata.distributions()
]
print(json.dumps({"environment": environment, "distributions": distributions}))
"""


class LockError(ValueError):
    """uv.lock cannot be interpreted unambiguously."""


class ProbeError(RuntimeError):
    """The image could not be inspected."""


@dataclass(frozen=True)
class Probe:
    environment: dict[str, str]
    distributions: list[tuple[str, str]]


@dataclass(frozen=True)
class Report:
    missing: dict[str, str]
    mismatched: dict[str, tuple[str, list[str]]]
    unexpected: dict[str, list[str]]
    duplicated: dict[str, list[str]]

    @property
    def ok(self) -> bool:
        return not (self.missing or self.mismatched or self.unexpected or self.duplicated)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "missing": self.missing,
            "mismatched": {
                name: {"locked": locked, "installed": installed}
                for name, (locked, installed) in self.mismatched.items()
            },
            "unexpected": self.unexpected,
            "duplicated": self.duplicated,
        }


def normalize(name: str) -> str:
    """PEP 503 name normalization (uv.lock already stores normalized names)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _root_package(packages: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    roots = [
        package
        for package in packages
        if package.get("source", {}).get("editable") == "." or package.get("source", {}).get("virtual") == "."
    ]
    if len(roots) != 1:
        raise LockError(f"expected exactly one root project in uv.lock, found {len(roots)}")
    return roots[0]


def _resolve(index: Mapping[str, list[Mapping[str, Any]]], edge: Mapping[str, Any]) -> Mapping[str, Any]:
    candidates = index.get(normalize(edge["name"]), [])
    if "version" in edge:
        candidates = [package for package in candidates if package["version"] == edge["version"]]
    if len(candidates) != 1:
        raise LockError(f"dependency {edge['name']!r} does not resolve to exactly one uv.lock package")
    return candidates[0]


def locked_closure(
    lock: Mapping[str, Any], environment: Mapping[str, str], groups: Iterable[str] = ()
) -> dict[str, str]:
    """Return {normalized name: locked version} installed for ``environment``.

    Starts at the root project's runtime dependencies plus the named dependency
    groups, follows requested extras, and skips edges whose marker is false.
    The root project itself is not part of the closure.
    """
    packages = lock.get("package", [])
    index: dict[str, list[Mapping[str, Any]]] = {}
    for package in packages:
        index.setdefault(normalize(package["name"]), []).append(package)
    root = _root_package(packages)

    pending = list(root.get("dependencies", []))
    for group in groups:
        group_edges = root.get("dev-dependencies", {}).get(group)
        if group_edges is None:
            raise LockError(f"uv.lock has no dependency group {group!r}")
        pending.extend(group_edges)

    marker_environment = {**environment, "extra": ""}
    root_name = normalize(root["name"])
    closure: dict[str, str] = {}
    visited: set[tuple[str, str, tuple[str, ...]]] = set()
    while pending:
        edge = pending.pop()
        marker = edge.get("marker")
        if marker and not Marker(marker).evaluate(marker_environment):
            continue
        package = _resolve(index, edge)
        name = normalize(package["name"])
        if name == root_name:
            continue
        version = package["version"]
        if closure.setdefault(name, version) != version:
            raise LockError(f"{name} resolves to both {closure[name]} and {version} for this environment")
        extras = tuple(edge.get("extra", ()))
        if (name, version, extras) in visited:
            continue
        visited.add((name, version, extras))
        pending.extend(package.get("dependencies", []))
        optional = package.get("optional-dependencies", {})
        for extra in extras:
            pending.extend(optional.get(extra, []))
    return closure


def _same_version(installed: str, locked: str) -> bool:
    try:
        return Version(installed) == Version(locked)
    except InvalidVersion:
        return installed == locked


def compare(
    required: Mapping[str, str], allowed: Mapping[str, str], distributions: Iterable[tuple[str, str]]
) -> Report:
    """Compare installed distributions with the locked closures.

    ``required`` must be installed at the locked version; ``allowed`` may be
    installed, but only at the locked version. Everything else is unexpected,
    except the base image's own installer.
    """
    installed: dict[str, list[str]] = {}
    for raw_name, version in distributions:
        installed.setdefault(normalize(raw_name) or "<unnamed dist-info>", []).append(version)
    locked = {**allowed, **required}

    missing = {name: version for name, version in sorted(required.items()) if name not in installed}
    mismatched: dict[str, tuple[str, list[str]]] = {}
    unexpected: dict[str, list[str]] = {}
    duplicated = {name: sorted(versions) for name, versions in sorted(installed.items()) if len(versions) > 1}
    for name, versions in sorted(installed.items()):
        if name not in locked:
            if name not in BASE_IMAGE_DISTRIBUTIONS:
                unexpected[name] = sorted(versions)
        elif not all(_same_version(version, locked[name]) for version in versions):
            mismatched[name] = (locked[name], sorted(versions))
    return Report(missing=missing, mismatched=mismatched, unexpected=unexpected, duplicated=duplicated)


def probe_image(image: str, docker: str = "docker") -> Probe:
    """Read the marker environment and installed distributions of ``image``."""
    command = [docker, "run", "--rm", "--network", "none", "--entrypoint", "python", image, "-c", PROBE]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProbeError(f"cannot run {docker}: {exc}") from exc
    if completed.returncode != 0:
        raise ProbeError(f"probe exited {completed.returncode}: {completed.stderr.strip()[-2000:]}")
    return parse_probe(completed.stdout)


def parse_probe(stdout: str) -> Probe:
    try:
        payload = json.loads(stdout)
        environment = {str(key): str(value) for key, value in payload["environment"].items()}
        distributions = [(str(name), str(version)) for name, version in payload["distributions"]]
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ProbeError(f"probe output is not the expected JSON: {exc}") from exc
    return Probe(environment=environment, distributions=distributions)


def _render(report: Report, image: str, required: Mapping[str, str], allowed: Mapping[str, str]) -> str:
    if report.ok:
        return (
            f"OK {image}: installed distributions match uv.lock "
            f"({len(required)} runtime, {len(allowed)} allowed from groups)"
        )
    lines = [f"DRIFT {image}: installed distributions do not match uv.lock"]
    lines += [f"  missing     {name}=={version}" for name, version in report.missing.items()]
    lines += [
        f"  mismatched  {name}: locked {locked}, installed {', '.join(installed)}"
        for name, (locked, installed) in report.mismatched.items()
    ]
    lines += [f"  unexpected  {name}=={', '.join(versions)}" for name, versions in report.unexpected.items()]
    lines += [f"  duplicated  {name}: {', '.join(versions)}" for name, versions in report.duplicated.items()]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None, probe: Callable[[str], Probe] = probe_image) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--image", required=True, help="built image tag or ID to inspect")
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK, help="uv.lock path (default: backend/uv.lock)")
    parser.add_argument(
        "--allow-group",
        action="append",
        default=[],
        metavar="GROUP",
        help="dependency group whose packages may be installed, at locked versions (repeatable)",
    )
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)

    try:
        lock = tomllib.loads(args.lock.read_text(encoding="utf-8"))
        observed = probe(args.image)
        required = locked_closure(lock, observed.environment)
        grouped = locked_closure(lock, observed.environment, groups=args.allow_group)
    except (OSError, tomllib.TOMLDecodeError, LockError, ProbeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    allowed = {name: version for name, version in grouped.items() if name not in required}
    report = compare(required, allowed, observed.distributions)

    if args.json:
        print(json.dumps({"image": args.image, **report.as_dict()}, indent=2, sort_keys=True))
    else:
        print(_render(report, args.image, required, allowed))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
