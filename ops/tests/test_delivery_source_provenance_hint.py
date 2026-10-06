from __future__ import annotations

import sys
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters import source_provenance


def test_control_plane_drift_error_explains_safe_bootstrap_route(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()

    def fake_inspect(root: Path) -> source_provenance.CheckoutProvenance:
        return source_provenance.CheckoutProvenance(
            root=root,
            head_sha="a" * 40,
            clean=True,
            control_plane_fingerprint="source" if root == source else "target",
        )

    monkeypatch.setattr(source_provenance, "inspect_checkout", fake_inspect)

    problem = source_provenance.source_compatibility_problem(
        source_root=source,
        target_repo=target,
    )

    assert problem is not None
    assert "source fingerprint differs from target repo" in problem
    assert f"{target / 'ops' / 'delivery.py'}" in problem
    assert "merge the change first" in problem
