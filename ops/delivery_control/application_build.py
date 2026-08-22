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
    """Resolve the unique protected ``main`` checkout for mutations.

    ``delivery.py`` is intentionally runnable from an owner worktree so it
    loads the same control-plane code that will publish the handback.  Git
    mutation commands must nevertheless run from the checked-out ``main``
    worktree.  Falling back to the owner worktree is unsafe: cleanup would
    later identify its own checkout as canonical and leave a published lane in
    ``cleanup_pending`` after the PR was already created.

    Non-repository paths remain supported for composition tests.  A real
    repository without exactly one checked-out ``main`` fails before any
    GitHub or registry mutation.
    """

    try:
        main_worktrees = tuple(
            item for item in probe.list_worktrees() if item.branch == "main"
        )
    except AdapterError:
        return source_repo
    if len(main_worktrees) != 1:
        if not main_worktrees:
            raise AdapterError(
                "canonical main checkout is unavailable; check out main before "
                "running delivery mutations"
            )
        raise AdapterError(
            "canonical main checkout is ambiguous; exactly one main worktree "
            "is required before running delivery mutations"
        )
    return main_worktrees[0].path


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
