from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "constitution_lint", ROOT / "ops" / "constitution_lint.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_machine_law_references_are_dynamic_and_missing_refs_fail(tmp_path):
    assert MODULE.validate_constitution(ROOT / "CLAUDE.md") == []

    source = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    sandbox = tmp_path / "repo"
    sandbox.mkdir()
    for _, _, relative, _ in MODULE.machine_references(source):
        target = sandbox / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)

    missing_file = sandbox / "missing-file.md"
    missing_file.write_text(source.replace(
        "ops/devops_kg_safe.sh:is_blocked_run",
        "ops/does-not-exist.sh:is_blocked_run",
        1,
    ), encoding="utf-8")
    errors = MODULE.validate_constitution(missing_file)
    assert any("ops/does-not-exist.sh" in error for error in errors)

    missing_symbol = sandbox / "missing-symbol.md"
    missing_symbol.write_text(source.replace(
        "ops/devops_kg_safe.sh:is_blocked_run",
        "ops/devops_kg_safe.sh:missing_guard_symbol",
        1,
    ), encoding="utf-8")
    errors = MODULE.validate_constitution(missing_symbol)
    assert any("missing_guard_symbol" in error for error in errors)

    law9 = next(
        line for line in source.splitlines()
        if line.lstrip().startswith("9. **工具摩擦優先修工具**")
    )
    without_law9 = sandbox / "without-law9.md"
    without_law9.write_text(
        "\n".join(line for line in source.splitlines() if line != law9) + "\n",
        encoding="utf-8",
    )
    errors = MODULE.validate_constitution(without_law9)
    assert any("exactly 9 iron laws" in error for error in errors)

    invalid_marker = sandbox / "invalid-marker.md"
    invalid_marker.write_text(
        source.replace("9. **工具摩擦優先修工具** `[prompt]`",
                       "9. **工具摩擦優先修工具** `[operator-only]`", 1),
        encoding="utf-8",
    )
    errors = MODULE.validate_constitution(invalid_marker)
    assert any("primary enforcement marker" in error for error in errors)
