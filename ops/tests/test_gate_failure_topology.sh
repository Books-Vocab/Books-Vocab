#!/usr/bin/env bash
set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/../.." && pwd)"
UV_BIN="${UV_BIN:-}"
if [[ -z "$UV_BIN" ]]; then
  if [[ -x "$HOME/.local/bin/uv" ]]; then UV_BIN="$HOME/.local/bin/uv"; else UV_BIN="uv"; fi
fi

"$UV_BIN" run --no-project --python 3.13 --with pytest python - "$WORKSPACE" <<'PY'
from __future__ import annotations

from collections import Counter
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(sys.argv[1])
ROUTES = {
    "exit-code": (
        ("ops/tests/test_streaming_command.py", (
            "test_signal_return_code_is_preserved",
            "test_timeout_is_reported_as_its_own_fact_not_only_as_a_return_code",
        )),
        ("ops/tests/test_task_registry.py", (
            "test_streaming_command_spawn_failure_has_terminal_outcome",
        )),
    ),
    "summary": (
        ("ops/tests/test_streaming_command.py", (
            "test_completed_process_returns_the_monotonic_elapsed",
        )),
        ("ops/tests/test_task_registry.py", (
            "test_command_identity_is_non_sensitive",
            "test_streaming_command_records_start_heartbeat_finish_without_raw_argv",
        )),
    ),
    "heartbeat": (
        ("ops/tests/test_streaming_command.py", (
            "test_progress_contract_and_separate_streams",
            "test_silent_child_heartbeat_reports_stalled_with_stable_field_order",
            "test_busy_child_heartbeat_never_reports_stalled",
            "test_idle_is_measured_from_the_byte_not_from_the_beat",
            "test_the_chosen_lc_ctype_is_visible_in_the_progress_stream",
        )),
    ),
    "timeout-cleanup": (
        ("ops/tests/test_streaming_command.py", (
            "test_interrupt_terminates_child_process_group",
            "test_interrupt_during_spawned_progress_terminates_process_group",
            "test_timeout_terminates_child_process_group",
            "test_timeout_kills_grandchild_after_group_leader_exits",
        )),
        ("ops/tests/test_task_registry.py", (
            "test_cleanup_rejects_every_unsafe_shape_without_signalling",
            "test_dry_run_stale_cleanup_does_not_signal_or_finish",
            "test_stale_owned_cleanup_only_terminates_named_group_and_records_outcome",
        )),
    ),
    "contention-inconclusive": (
        ("ops/tests/test_task_registry.py", (
            "test_parallel_registry_writes_preserve_two_lifecycles",
            "test_two_parallel_streaming_commands_finish_without_lost_ledger_rows",
        )),
    ),
    "stdout-stderr": (
        ("ops/tests/test_streaming_command.py", (
            "test_direct_script_path_imports_sibling_ops_modules_from_repo_root",
            "test_large_dual_stream_output_is_drained_and_bounded",
            "test_progress_never_logs_raw_command_arguments",
            "test_child_lc_ctype_is_chosen_by_the_tool_not_inherited",
            "test_child_lc_ctype_choice_survives_a_caller_who_set_lc_all",
            "test_lc_ctype_choice_makes_children_parse_shell_the_strict_way",
            "test_an_explicit_env_argument_still_gets_the_chosen_lc_ctype",
        )),
    ),
}

SOURCE_FILES = tuple({path for groups in ROUTES.values() for path, _ in groups})


def selectors(groups: tuple[tuple[str, tuple[str, ...]], ...]) -> list[str]:
    return [f"{path}::{name}" for path, names in groups for name in names]


def collect(args: list[str], *, label: str) -> tuple[str, ...]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "--collect-only", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 5:
        raise AssertionError(f"zero-selector route: {label}")
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    nodeids = tuple(
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip().startswith("ops/tests/") and "::" in line
    )
    if not nodeids:
        raise AssertionError(f"zero-selector route: {label}")
    return nodeids


full = Counter(collect(list(SOURCE_FILES), label="full compatibility set"))
assert full and all(count == 1 for count in full.values()), full
split = Counter()
for route, groups in ROUTES.items():
    route_selectors = selectors(groups)
    nodes = collect(route_selectors, label=route)
    split.update(nodes)
    print(f"route={route} phase=collect nodes={len(nodes)}")
    print(f"route={route} phase=run")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         *route_selectors],
        cwd=ROOT,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"route={route} execution rc={result.returncode}")

assert split == full, {"full": full, "split": split}
assert all(count == 1 for count in split.values()), split

with tempfile.TemporaryDirectory(prefix="kg-gate-topology-") as temp:
    empty = Path(temp) / "test_empty_selector.py"
    empty.write_text("VALUE = 1\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "--collect-only", str(empty)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 5, result

legacy = (ROOT / "ops/tests/test_gate_can_fail.sh").read_text(encoding="utf-8")
for marker in (
    'section "every block-level gate declares BOTH directions"',
    'section "cheap proofs are executed in BOTH directions, not asserted"',
    'section "expensive gates: green read from recorded behaviour, never assumed"',
    'section "what is declared cheap was actually executed"',
):
    assert legacy.count(marker) == 1, marker
assert legacy.count("ops/tests/test_gate_failure_topology.sh") == 1
print(f"gate-failure-topology: {len(ROUTES)} routes, {sum(full.values())} nodeids, zero-selector=fail-closed")
PY
