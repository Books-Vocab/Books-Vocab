from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "ops/tests/ops_group_chain.py"
SPEC = importlib.util.spec_from_file_location("ops_group_chain", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_parse_dispatcher_keeps_multiline_group_bodies_separate() -> None:
    source = """
run_one() {
  case "$1" in
    alpha) ./ops/alpha.sh ;;
    beta)
      ./ops/beta.sh &&
      uv run pytest ops/tests/test_beta.py
      ;;
  esac
}
"""

    arms = MODULE.parse_dispatcher(source)

    assert "./ops/alpha.sh" in arms["alpha"]
    assert "./ops/beta.sh" in arms["beta"]
    assert "ops/tests/test_beta.py" in arms["beta"]
    assert "beta" not in arms["alpha"]


def test_absolute_calls_ignore_comments_strings_and_fixture_payloads(tmp_path: Path) -> None:
    root = tmp_path
    dispatcher = root / "ops/test_ops.sh"
    script = root / "ops/demo.sh"
    dispatcher.parent.mkdir(parents=True)
    dispatcher.write_text(
        'run_one() {\n  case "$1" in\n    demo) ./ops/demo.sh ;;\n  esac\n}\n'
    )
    script.write_text(
        """# /usr/bin/not-a-call
echo \"/usr/bin/not-a-call\"
cat <<'JSON'
{\"path\":\"/System/Library/not-a-call\"}
JSON
for candidate in /usr/bin/not-a-call \\
                    /usr/bin/not-a-call-too; do
  : \"$candidate\"
done
/usr/bin/real-command --flag
/usr/bin/\"${args[@]}\"
true && /usr/bin/after-and
"""
    )

    calls = MODULE.scan_group(root, "demo")

    assert [call.path for call in calls] == [
        "/usr/bin/real-command",
        '/usr/bin/"${args[@]}"',
        "/usr/bin/after-and",
    ]
    assert all(call.source == Path("ops/demo.sh") for call in calls)


def test_current_ios_group_exposes_absolute_log_calls() -> None:
    calls = MODULE.scan_group(ROOT, "ios-ops")

    assert any(
        call.source == Path("ops/lib/ios_ops_logs.sh")
        and call.path.startswith("/usr/bin/")
        for call in calls
    )


def test_case_arms_covers_every_group_in_test_ops() -> None:
    arms = MODULE.case_arms()

    # The shared baseline has 55 DEFAULT_TESTS arms plus the two optional arms.
    # Keep the count pinned so adding an arm requires this inventory test to move.
    assert len(arms) == 57
    assert {"ios-ops", "lldb-forensics", "ops-ci-coverage", "kg-board", "asc", "release-surfaces"} <= set(arms)
    assert "*" not in arms


def test_ios_ops_chain_reaches_ios_ops_logs_and_flags_absolute_calls() -> None:
    chain = MODULE.chain("ios-ops")

    assert ROOT / "ops/lib/ios_ops_logs.sh" in chain
    assert ROOT / "ops/ios_ops.sh" in chain
    hits = MODULE.abs_calls("ios-ops")
    assert hits
    assert {67, 90, 165, 209} <= {
        line for path, line, _ in hits if path.name == "ios_ops_logs.sh"
    }


def test_lldb_forensics_chain_has_no_absolute_path_invocation() -> None:
    chain = MODULE.chain("lldb-forensics")

    assert {
        ROOT / "ops/install_lldb_forensics.sh",
        ROOT / "ops/lldb_crash_forensics.py",
        ROOT / "ops/tests/test_lldb_crash_forensics.sh",
    } <= set(chain)
    assert MODULE.abs_calls("lldb-forensics") == []


def test_abs_calls_in_file_ignores_shebang_comment_and_string_literals(tmp_path: Path) -> None:
    path = tmp_path / "fixture.sh"
    path.write_text(
        """#!/usr/bin/env bash
# 註解裡提到 /usr/bin/log
printf '/usr/bin/%s' "$args"
echo "run /usr/bin/log"
[[ -x /usr/bin/log ]] && echo yes
LOGBIN=/usr/bin/log
/usr/bin/log stream --style compact
  /usr/bin/"${args[@]}"
x="$(/usr/libexec/PlistBuddy -c Print f)"
 exec /bin/mv "$@"
"""
    )

    assert [line for line, _ in MODULE.abs_calls_in_file(path)] == [7, 8, 9, 10]


def test_coverage_gate_declares_and_wires_the_scanner() -> None:
    coverage = (ROOT / "ops/tests/test_ops_ci_coverage.sh").read_text()
    assert "PATH_FALSIFY_UNSOUND=(" in coverage
    assert "absolute-path invocations in a bin-* chain are declared" in coverage
    assert "ops_group_chain.py abs-calls" in coverage
    assert "not proof of it" in coverage
    assert "要補得掃出 group 的真實命令鏈，屬 IMP-0059" not in coverage
    assert "這個缺口**沒有補**" not in coverage

    dispatcher = (ROOT / "ops/test_ops.sh").read_text()
    arm = dispatcher.split("ops-ci-coverage)", 1)[1].split(";;", 1)[0]
    assert "ops/tests/test_ops_group_chain.py" in arm


def test_kg_board_group_covers_git_tree_regression() -> None:
    """Every KG board test module must be in the default kg-board arm."""

    dispatcher = (ROOT / "ops/test_ops.sh").read_text()
    arm = dispatcher.split("kg-board)", 1)[1].split(";;", 1)[0]

    assert "ops/tests/test_kg_board_git_tree.py" in arm
