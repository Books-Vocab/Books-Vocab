"""Composition root for the deterministic delivery application."""

from __future__ import annotations

from pathlib import Path

import worktree_registry

from .adapters.errors import AdapterError
from .adapters.git_cli import GitCliAdapter
from .adapters.github_cli import GitHubCliAdapter
from .adapters.module_runner import ModuleCommandRunner
from .adapters.registry import RegistryCliAdapter
from .adapters.runtime import RuntimeStatusMap
from .adapters.telemetry_ndjson import TelemetryNdjsonAdapter
from .application_services import DeliveryApplication

CONTROL_PLANE_OPS = Path(__file__).resolve().parents[1]


def _canonical_repo(source_repo: Path, *, probe: GitCliAdapter) -> Path:
    """Resolve the protected main checkout without changing source provenance.

    ``delivery.py`` is intentionally runnable from an owner worktree so it
    loads the same control-plane code that will publish the handback.  Git
    mutation commands, however, must still treat the linked ``main`` checkout
    as canonical; otherwise publishing a feature worktree tries to remove the
    checkout that the command is currently using.  Non-repository paths remain
    supported for composition tests and fail back to their original path.
    """

    try:
        main_worktrees = tuple(
            item for item in probe.list_worktrees() if item.branch == "main"
        )
    except AdapterError:
        return source_repo
    return main_worktrees[0].path if len(main_worktrees) == 1 else source_repo


def build_application(
    *, repo: Path, runtime_status_file: Path | None = None
) -> DeliveryApplication:
    resolved = repo.expanduser().resolve()
    source_probe = GitCliAdapter(repo=resolved)
    canonical_repo = _canonical_repo(resolved, probe=source_probe)
    registry_script = CONTROL_PLANE_OPS / "worktree_registry.py"
    return DeliveryApplication(
        repo=canonical_repo,
        git=GitCliAdapter(repo=canonical_repo),
        github=GitHubCliAdapter(repo=canonical_repo),
        registry=RegistryCliAdapter(
            script_path=registry_script,
            state_path=worktree_registry.default_state_path(resolved),
            runner=ModuleCommandRunner(
                executable=registry_script,
                main=worktree_registry.main,
                source_root=CONTROL_PLANE_OPS.parent,
                target_repo=canonical_repo,
            ),
        ),
        runtime=RuntimeStatusMap.from_file(runtime_status_file),
        telemetry=TelemetryNdjsonAdapter(
            canonical_repo / ".cache" / "delivery_telemetry.ndjson"
        ),
    )


__all__ = ["build_application"]
