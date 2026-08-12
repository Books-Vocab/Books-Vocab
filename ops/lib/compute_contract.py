"""Fail-closed validation and resolution for typed local compute profiles.

The registry is JSON-in-YAML so it remains consumable without a third-party YAML
dependency.  A profile is metadata only: this module never spawns a process,
opens a network connection, or writes a source tree.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


SCHEMA = "kg.compute_profiles.v1"
VERSION = 1
_DEFAULT_REGISTRY = Path(__file__).resolve().parents[1] / "compute_profiles.yml"
_SAFE_SIDE_EFFECTS = {"repo-read", "artifact-write"}
_FORBIDDEN_SIDE_EFFECTS = {
    "production-write", "credential-read", "docker-socket", "production-network",
    "localhost-production", "deploy", "migration", "ops-edit", "cutover", "sync", "release",
}
_SAFE_SANDBOX_POLICIES = {"uv-no-project", "repo-readonly"}
_SHELL_INTERPRETERS = {"sh", "bash", "dash", "zsh", "ksh", "fish", "pwsh", "powershell", "cmd"}
_PLACEHOLDER = re.compile(r"^\{([a-z][a-z0-9_]*)\}$")
_PATH_VALUE = re.compile(r"^[A-Za-z0-9_./ -]+$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class ContractError(ValueError):
    """A named contract refusal suitable for an agent-facing receipt."""


def _fail(code: str, detail: str = "") -> None:
    suffix = f": {detail}" if detail else ""
    raise ContractError(f"{code}{suffix}")


def canonical_spec(spec: dict[str, Any]) -> str:
    """Return deterministic UTF-8 JSON bytes represented as text."""
    return json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def spec_digest(spec: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_spec(spec).encode("utf-8")).hexdigest()


def load_profile_registry(path: Path | str = _DEFAULT_REGISTRY) -> dict[str, Any]:
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        _fail("registry-missing", str(exc))
    try:
        registry = json.loads(raw)
    except json.JSONDecodeError as exc:
        _fail("registry-json", str(exc))
    if not isinstance(registry, dict):
        _fail("registry-schema", "root must be an object")
    if registry.get("schema") != SCHEMA or registry.get("version") != VERSION:
        _fail("registry-schema", f"expected {SCHEMA} v{VERSION}")
    profiles = registry.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        _fail("registry-profiles", "profiles must be a non-empty object")
    for name, profile in profiles.items():
        validate_profile(profile, name=name)
    return registry


def _require_string(obj: dict[str, Any], key: str, *, nonempty: bool = True) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or (nonempty and not value):
        _fail("invalid-field", key)
    return value


def validate_profile(profile: Any, *, name: str = "<profile>") -> dict[str, Any]:
    if not isinstance(profile, dict):
        _fail("profile-schema", name)
    allowed = {
        "command", "parameters", "source_kind", "required_capabilities",
        "resource_class", "timeout_seconds", "remote_eligible",
        "minimum_tier",
        "git_metadata_required", "side_effects", "network_policy",
        "sandbox_policy", "runner_image_digest", "artifact_contract",
    }
    unknown = sorted(set(profile) - allowed)
    if unknown:
        _fail("forbidden-field", ",".join(unknown))
    command = profile.get("command")
    if not isinstance(command, dict) or set(command) != {"argv", "shell"}:
        _fail("forbidden-field", "command-shape")
    argv = command.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
        _fail("literal-argv", name)
    if command.get("shell") is not False:
        _fail("shell-disabled", name)
    command_tokens = {Path(token).name for token in argv if token and not token.startswith("-")}
    if (
        command_tokens & _SHELL_INTERPRETERS
        or "env" in command_tokens
        or any(token in {"-c", "--command"} for token in argv)
    ):
        _fail("shell-disabled", name)
    params = profile.get("parameters")
    if not isinstance(params, dict):
        _fail("parameters-schema", name)
    placeholders = set()
    for token in argv:
        match = _PLACEHOLDER.match(token)
        if match:
            placeholders.add(match.group(1))
        elif "{" in token or "}" in token:
            _fail("literal-argv", token)
    if placeholders != set(params):
        _fail("parameter-contract", name)
    for key, definition in params.items():
        if not isinstance(definition, dict) or definition.get("type") != "relative-path":
            _fail("parameter-schema", key)
        prefix = _require_string(definition, "prefix")
        parts = [part for part in prefix.split("/") if part]
        if (
            not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*/?", prefix)
            or prefix.startswith(("/", "~", "\\"))
            or any(part in {".", ".."} for part in parts)
        ):
            _fail("parameter-schema", key)
        _require_string(definition, "suffix")
        if not isinstance(definition.get("max_length"), int) or definition["max_length"] <= 0:
            _fail("parameter-schema", key)
    source_kind = _require_string(profile, "source_kind")
    if source_kind != "clean-committed-tree":
        _fail("source-kind", source_kind)
    caps = profile.get("required_capabilities")
    if not isinstance(caps, list) or not caps or not all(isinstance(x, str) and x for x in caps):
        _fail("capability-contract", name)
    if not isinstance(profile.get("resource_class"), str) or not profile["resource_class"]:
        _fail("invalid-field", "resource_class")
    if profile.get("minimum_tier") not in {"observer", "operator"}:
        _fail("invalid-field", "minimum_tier")
    if not isinstance(profile.get("timeout_seconds"), int) or profile["timeout_seconds"] <= 0:
        _fail("invalid-field", "timeout_seconds")
    if profile.get("remote_eligible") is not False:
        _fail("remote-ineligible", name)
    if profile.get("git_metadata_required") is not False:
        _fail("git-metadata", name)
    effects = profile.get("side_effects")
    if not isinstance(effects, list) or not effects or not all(isinstance(x, str) for x in effects):
        _fail("side-effects", name)
    forbidden = sorted(set(effects) & _FORBIDDEN_SIDE_EFFECTS)
    if forbidden or not set(effects) <= _SAFE_SIDE_EFFECTS:
        _fail("forbidden-side-effect", ",".join(forbidden or sorted(set(effects) - _SAFE_SIDE_EFFECTS)))
    if profile.get("network_policy") != "none":
        _fail("network-policy", name)
    sandbox = _require_string(profile, "sandbox_policy")
    if sandbox not in _SAFE_SANDBOX_POLICIES:
        _fail("invalid-field", "sandbox_policy")
    image = profile.get("runner_image_digest")
    if not isinstance(image, str) or not image:
        _fail("runner-image-digest", name)
    if not _DIGEST.fullmatch(image):
        _fail("runner-image-digest", name)
    _require_string(profile, "artifact_contract")
    return profile


def _resolve_parameter(name: str, value: Any, definition: dict[str, Any]) -> str:
    if not isinstance(value, str) or not value:
        _fail("invalid-parameter", name)
    if len(value) > definition["max_length"]:
        _fail("too-long", name)
    if value.startswith("-"):
        _fail("leading-dash", name)
    if not _PATH_VALUE.fullmatch(value) or any(token in value for token in ("..", "//")):
        if ".." in value:
            _fail("path-traversal", name)
        if any(c in value for c in ("\n", "\r", "\t")):
            _fail("control-character", name)
        if any(token in value for token in ("`", "$(", ";")):
            _fail("shell-token", name)
        if any(ord(c) > 127 for c in value):
            _fail("non-ascii", name)
        _fail("invalid-parameter", name)
    if not value.startswith(definition["prefix"]):
        _fail("path-prefix", name)
    if not value.endswith(definition["suffix"]):
        _fail("path-suffix", name)
    return value


def resolve_profile(
    name: str,
    params: dict[str, Any],
    *,
    source_dirty: bool = False,
    available_capabilities: set[str] | None = None,
    registry_path: Path | str = _DEFAULT_REGISTRY,
) -> dict[str, Any]:
    registry = load_profile_registry(registry_path)
    profiles = registry["profiles"]
    if name not in profiles:
        _fail("unknown-profile", name)
    profile = profiles[name]
    if not isinstance(params, dict):
        _fail("parameters-schema", name)
    expected = set(profile["parameters"])
    extra = sorted(set(params) - expected)
    if extra:
        _fail("extra-parameter", ",".join(extra))
    missing = sorted(expected - set(params))
    if missing:
        _fail("missing-parameter", ",".join(missing))
    if source_dirty:
        _fail("dirty-source", name)
    required = set(profile["required_capabilities"])
    if available_capabilities is not None and not required <= set(available_capabilities):
        _fail("missing-capability", ",".join(sorted(required - set(available_capabilities))))
    resolved = {key: _resolve_parameter(key, params[key], definition) for key, definition in profile["parameters"].items()}
    argv = [resolved.get(match.group(1), token) if (match := _PLACEHOLDER.match(token)) else token
            for token in profile["command"]["argv"]]
    spec = {
        "profile": name,
        "version": VERSION,
        "argv": argv,
        "shell": False,
        "source_kind": profile["source_kind"],
        "required_capabilities": sorted(required),
        "resource_class": profile["resource_class"],
        "minimum_tier": profile["minimum_tier"],
        "timeout_seconds": profile["timeout_seconds"],
        "remote_eligible": False,
        "git_metadata_required": False,
        "side_effects": list(profile["side_effects"]),
        "network_policy": profile["network_policy"],
        "sandbox_policy": profile["sandbox_policy"],
        "runner_image_digest": profile["runner_image_digest"],
        "artifact_contract": profile["artifact_contract"],
        "parameters": resolved,
    }
    return {
        "profile": name,
        "argv": argv,
        "shell": False,
        "spec": spec,
        "spec_digest": spec_digest(spec),
    }
