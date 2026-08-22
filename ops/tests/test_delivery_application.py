from __future__ import annotations

import sys
from dataclasses import fields
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.registry import RegistryCliAdapter
from delivery_control.adapters.telemetry_ndjson import TelemetryNdjsonAdapter
from delivery_control.application import DeliveryApplication, build_application


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
