from __future__ import annotations

import subprocess
import sys
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.registry import RegistryCliAdapter
from delivery_control.adapters.telemetry_ndjson import TelemetryNdjsonAdapter
from delivery_control.application import DeliveryApplication, build_application
from delivery_control.controller.dogfood import DogfoodProfile
from delivery_control.controller.metrics import MergeCadence


def test_application_public_facade_preserves_constructor_contract() -> None:
    assert tuple(field.name for field in fields(DeliveryApplication)) == (
        "repo",
        "git",
        "github",
        "registry",
        "runtime",
        "telemetry",
        "clock",
    )
    assert DeliveryApplication.__dataclass_params__.frozen is True
    assert callable(DeliveryApplication.trigger_required)


def test_application_uses_co_versioned_registry_executable(tmp_path: Path) -> None:
    application = build_application(repo=tmp_path)

    assert isinstance(application.registry, RegistryCliAdapter)
    assert application.registry.script_path == OPS / "worktree_registry.py"
    assert application.registry.script_path != tmp_path / "ops" / "worktree_registry.py"
    assert (
        application.registry.state_path
        == tmp_path / ".cache" / "worktree_registry.json"
    )
    assert isinstance(application.telemetry, TelemetryNdjsonAdapter)
    assert (
        application.telemetry.path == tmp_path / ".cache" / "delivery_telemetry.ndjson"
    )
    assert application.registry.runner.target_repo == tmp_path.resolve()
    assert application.registry.runner.source_root == OPS.parent.resolve()


def test_application_uses_main_checkout_for_cleanup_from_linked_worktree(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    source_worktree = tmp_path / "source"
    repository.mkdir()
    subprocess.run(("git", "init", "-b", "main", str(repository)), check=True)
    subprocess.run(
        ("git", "-C", str(repository), "config", "user.email", "test@example.com"),
        check=True,
    )
    subprocess.run(
        ("git", "-C", str(repository), "config", "user.name", "Test"),
        check=True,
    )
    (repository / "README").write_text("test\n", encoding="utf-8")
    subprocess.run(("git", "-C", str(repository), "add", "README"), check=True)
    subprocess.run(("git", "-C", str(repository), "commit", "-m", "init"), check=True)
    subprocess.run(
        (
            "git",
            "-C",
            str(repository),
            "worktree",
            "add",
            "-b",
            "feature",
            str(source_worktree),
        ),
        check=True,
    )

    application = build_application(repo=source_worktree)

    assert application.repo == repository.resolve()
    assert application.git.repo == repository.resolve()
    assert application.registry.runner.target_repo == repository.resolve()


def test_dogfood_preflight_measures_the_configured_promotion_window(
    tmp_path: Path,
) -> None:
    git = Mock()
    git.canonical_checkout.return_value = SimpleNamespace(branch="main", clean=True)
    git.origin_main_sha.return_value = "a" * 40
    git.local_main_sha.return_value = "a" * 40
    git.list_worktrees.return_value = ()

    github = Mock()
    github.branch_is_protected.return_value = True
    github.required_status_contexts.return_value = ("required",)
    github.merge_queue_enabled.return_value = True
    github.recent_merge_times.return_value = ()

    application = DeliveryApplication(
        repo=tmp_path,
        git=git,
        github=github,
        registry=Mock(),
        runtime=Mock(),
        telemetry=Mock(),
    )
    profile = DogfoodProfile(promotion_observation_seconds=600)
    cadence = MergeCadence(
        window_seconds=600,
        merged_count=0,
        merges_per_hour=0.0,
        p50_interval_seconds=None,
        p95_interval_seconds=None,
        seconds_since_last_merge=None,
    )

    with (
        patch.object(DeliveryApplication, "metrics", return_value=Mock()) as metrics,
        patch(
            "delivery_control.application_services.measure_merge_cadence",
            return_value=cadence,
        ) as measure,
        patch(
            "delivery_control.application_services.assess_dogfood_readiness",
            return_value=object(),
        ) as assess,
    ):
        result = application.dogfood_preflight(
            now=datetime(2026, 8, 22, tzinfo=UTC),
            profile=profile,
            supervision_worktree_paths=(Path("/supervision"),),
        )

    assert result is not None
    assert metrics.call_args.kwargs["supervision_worktree_paths"] == (
        Path("/supervision"),
    )
    assert measure.call_args.kwargs["window"] == timedelta(seconds=600)
    assert assess.call_args.kwargs["profile"] == profile


def test_plan_forwards_supervision_worktree_paths_to_metrics(tmp_path: Path) -> None:
    github = Mock()
    github.recent_merge_times.return_value = ()
    application = DeliveryApplication(
        repo=tmp_path,
        git=Mock(),
        github=github,
        registry=Mock(),
        runtime=Mock(),
        telemetry=Mock(),
    )
    with (
        patch.object(DeliveryApplication, "metrics", return_value=Mock()) as metrics,
        patch(
            "delivery_control.application_services.measure_merge_cadence",
            return_value=MergeCadence(
                window_seconds=3600,
                merged_count=0,
                merges_per_hour=0.0,
                p50_interval_seconds=None,
                p95_interval_seconds=None,
                seconds_since_last_merge=None,
            ),
        ),
        patch(
            "delivery_control.application_services.decide_capacity",
            return_value=object(),
        ),
    ):
        application.plan(
            now=datetime(2026, 8, 22, tzinfo=UTC),
            supervision_worktree_paths=(Path("/supervision"),),
        )

    assert metrics.call_args.kwargs["supervision_worktree_paths"] == (
        Path("/supervision"),
    )


def test_metrics_forwards_supervision_worktree_paths_to_inspect(
    tmp_path: Path,
) -> None:
    application = DeliveryApplication(
        repo=tmp_path,
        git=Mock(),
        github=Mock(),
        registry=Mock(),
        runtime=Mock(),
        telemetry=Mock(),
    )
    telemetry = Mock()
    telemetry.rolling.return_value = Mock()
    with (
        patch.object(DeliveryApplication, "inspect", return_value=Mock()) as inspect,
        patch.object(
            DeliveryApplication, "_operation_telemetry", return_value=telemetry
        ),
        patch(
            "delivery_control.application_services.measure_pipeline",
            return_value=object(),
        ) as measure,
    ):
        assert (
            application.metrics(supervision_worktree_paths=(Path("/supervision"),))
            is not None
        )

    assert inspect.call_args.kwargs["supervision_worktree_paths"] == (
        Path("/supervision"),
    )
    assert measure.call_args.kwargs["excluded_worktree_paths"] == (
        Path("/supervision"),
    )


def test_inspect_forwards_supervision_worktree_paths(tmp_path: Path) -> None:
    application = DeliveryApplication(
        repo=tmp_path,
        git=Mock(),
        github=Mock(),
        registry=Mock(),
        runtime=Mock(),
        telemetry=Mock(),
    )
    with patch(
        "delivery_control.application_services.inspect.InspectService"
    ) as service:
        service.return_value.inspect.return_value = object()
        assert (
            application.inspect(supervision_worktree_paths=(Path("/supervision"),))
            is not None
        )

    assert service.return_value.inspect.call_args.kwargs[
        "supervision_worktree_paths"
    ] == (Path("/supervision"),)
