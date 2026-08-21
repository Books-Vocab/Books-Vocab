from __future__ import annotations

import sys
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.module_runner import ModuleCommandRunner


def test_loaded_module_survives_source_executable_removal(tmp_path: Path) -> None:
    executable = tmp_path / "command.py"
    executable.touch()

    def main(argv: list[str] | None) -> int:
        assert argv == ["resolve", "--json"]
        print('{"status":"published"}')
        return 0

    runner = ModuleCommandRunner(executable=executable, main=main)
    executable.unlink()

    result = runner.run((str(executable), "resolve", "--json"))

    assert result.exit_code == 0
    assert result.stdout == '{"status":"published"}\n'
    assert result.stderr == ""
