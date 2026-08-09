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
