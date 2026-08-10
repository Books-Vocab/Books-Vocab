"""Architectural contracts for the ops-edit command boundary."""
from __future__ import annotations

import ast
from pathlib import Path

import kg.ops_edit_seed_commands as seed_commands
import kg.ops_edit_support as support


ROOT = Path(__file__).resolve().parents[1] / "src" / "kg"
COMMAND_MODULES = (
    "ops_edit_card_commands.py",
    "ops_edit_link_commands.py",
    "ops_edit_notebook_commands.py",
    "ops_edit_seed_commands.py",
    "ops_edit_user_commands.py",
)
FORBIDDEN_SUPPORT_FORWARD_NAMES = {
    "Any",
    "Path",
    "UTC",
    "datetime",
    "argparse",
    "csv",
    "json",
    "shutil",
    "sqlite3",
    "sys",
    "tarfile",
    "tempfile",
    "CardStore",
    "NotebookStore",
    "ReviewEventStore",
    "CardReviewState",
    "EditContext",
    "EditError",
    "LinkKind",
}


def _support_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module == "ops_edit_support":
            names.update(alias.name for alias in node.names)
    return names


def test_command_modules_do_not_use_support_as_a_namespace_router():
    for filename in COMMAND_MODULES:
        imported = _support_imports(ROOT / filename)
        assert not imported & FORBIDDEN_SUPPORT_FORWARD_NAMES, (
            filename,
            sorted(imported & FORBIDDEN_SUPPORT_FORWARD_NAMES),
        )


def test_support_does_not_publish_stdlib_types_or_store_compat_exports():
    exported = set(getattr(support, "__all__", ()))
    assert not exported & FORBIDDEN_SUPPORT_FORWARD_NAMES


def test_seed_has_explicit_spec_lifecycle_boundaries():
    for name in (
        "SeedSpec",
        "load_seed_spec",
        "prevalidate_seed",
        "build_seed_plan",
        "apply_seed",
        "verify_seed",
    ):
        assert hasattr(seed_commands, name), name
        assert callable(getattr(seed_commands, name)), name

    tree = ast.parse(
        (ROOT / "ops_edit_seed_commands.py").read_text(encoding="utf-8"),
        filename="ops_edit_seed_commands.py",
    )
    cmd_seed = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "cmd_seed"
    )
    nested = {
        node.name for node in ast.walk(cmd_seed) if isinstance(node, ast.FunctionDef)
    }
    assert nested == {"cmd_seed"}
