"""Composition root for the deterministic delivery application."""

from __future__ import annotations

from pathlib import Path

import worktree_registry

from .adapters.git_cli import GitCliAdapter
from .adapters.github_cli import GitHubCliAdapter
from .adapters.module_runner import ModuleCommandRunner
from .adapters.registry import RegistryCliAdapter
from .adapters.runtime import RuntimeStatusMap
from .adapters.telemetry_ndjson import TelemetryNdjsonAdapter
from .application_services import DeliveryApplication

CONTROL_PLANE_OPS = Path(__file__).resolve().parents[1]


def build_application(
    *, repo: Path, runtime_status_file: Path | None = None
) -> DeliveryApplication:
    resolved = repo.expanduser().resolve()
    registry_script = CONTROL_PLANE_OPS / "worktree_registry.py"
    return DeliveryApplication(
        repo=resolved,
        git=GitCliAdapter(repo=resolved),
        github=GitHubCliAdapter(repo=resolved),
        registry=RegistryCliAdapter(
            script_path=registry_script,
            state_path=resolved / ".cache" / "worktree_registry.json",
            runner=ModuleCommandRunner(
                executable=registry_script,
                main=worktree_registry.main,
            ),
        ),
        runtime=RuntimeStatusMap.from_file(runtime_status_file),
        telemetry=TelemetryNdjsonAdapter(
            resolved / ".cache" / "delivery_telemetry.ndjson"
        ),
    )


__all__ = ["build_application"]
