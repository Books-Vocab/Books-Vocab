"""CI skip budget for the backend suite (Issue #2115).

With ``--skip-allowlist=PATH`` every skipped test (including module-level
collection skips) must be listed in PATH with a linked Books-Vocab issue, or
the run fails. An allowlisted test that actually ran is a stale entry and also
fails. Entries that were not collected are ignored at runtime so subset runs
stay usable; ``test_skip_allowlist_gate.py`` checks they still exist.
xfail is an executed expectation, not a skip, and is not budgeted.

Without the option the plugin is inactive: local machines may lack optional
tools, CI may not.
"""

from __future__ import annotations

import json
import re
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import pytest

OPTION = "--skip-allowlist"
SCHEMA = "kg.backend_skip_allowlist.v1"
ISSUE_URL = re.compile(r"https://github\.com/Books-Vocab/Books-Vocab/issues/[1-9][0-9]*")
_ENTRY_KEYS = frozenset({"nodeid", "issue", "reason"})


class AllowlistError(ValueError):
    """The allowlist file cannot be trusted as a skip budget."""


@dataclass(frozen=True)
class AllowedSkip:
    nodeid: str
    issue: str
    reason: str


def load_allowlist(path: Path) -> dict[str, AllowedSkip]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AllowlistError(f"{path}: unreadable skip allowlist: {exc}") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema", "skips"} or payload["schema"] != SCHEMA:
        raise AllowlistError(f'{path}: expected {{"schema": "{SCHEMA}", "skips": [...]}}')
    if not isinstance(payload["skips"], list):
        raise AllowlistError(f'{path}: expected {{"schema": "{SCHEMA}", "skips": [...]}}')
    allowed: dict[str, AllowedSkip] = {}
    for index, entry in enumerate(payload["skips"]):
        where = f"{path}: skips[{index}]"
        if not isinstance(entry, dict) or set(entry) != _ENTRY_KEYS:
            raise AllowlistError(f"{where}: entry must have exactly {sorted(_ENTRY_KEYS)}")
        values = [entry["nodeid"], entry["issue"], entry["reason"]]
        if not all(isinstance(value, str) and value.strip() for value in values):
            raise AllowlistError(f"{where}: nodeid, issue and reason must be non-empty strings")
        nodeid, issue, reason = values
        if not ISSUE_URL.fullmatch(issue):
            raise AllowlistError(f"{where}: issue must link a Books-Vocab issue, got {issue!r}")
        if nodeid in allowed:
            raise AllowlistError(f"{where}: duplicate nodeid {nodeid!r}")
        allowed[nodeid] = AllowedSkip(nodeid, issue, reason)
    return allowed


def evaluate(skipped: dict[str, str], executed: set[str], allowlist: dict[str, AllowedSkip]) -> list[str]:
    violations = [
        f"unexpected skip: {nodeid} — {reason}" for nodeid, reason in sorted(skipped.items()) if nodeid not in allowlist
    ]
    violations += [
        f"stale allowlist entry: {nodeid} ran instead of skipping; remove it ({entry.issue})"
        for nodeid, entry in sorted(allowlist.items())
        if nodeid in executed and nodeid not in skipped
    ]
    return violations


def _skip_reason(report: pytest.CollectReport | pytest.TestReport) -> str:
    longrepr = report.longrepr
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        return str(longrepr[2])
    return str(longrepr)


class SkipAllowlistGate:
    def __init__(self, allowlist: dict[str, AllowedSkip], source: Path) -> None:
        self.allowlist = allowlist
        self.source = source
        self.skipped: dict[str, str] = {}
        self.executed: set[str] = set()
        self.violations: list[str] = []
        self.evaluated = False

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.skipped:
            self.skipped[report.nodeid] = _skip_reason(report)

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.skipped and not hasattr(report, "wasxfail"):
            self.skipped[report.nodeid] = _skip_reason(report)
        elif report.when == "call":
            self.executed.add(report.nodeid)

    @pytest.hookimpl(wrapper=True)
    def pytest_runtestloop(self, session: pytest.Session) -> Generator[None, object, object]:
        result = yield
        if not session.config.option.collectonly:
            self.evaluated = True
            self.violations = evaluate(self.skipped, self.executed, self.allowlist)
            if self.violations:
                session.testsfailed += 1
        return result

    def pytest_terminal_summary(self, terminalreporter: pytest.TerminalReporter) -> None:
        if not self.evaluated:
            return
        if not self.violations:
            terminalreporter.write_line(
                f"skip allowlist: {len(self.skipped)} skipped, all covered by {self.source} "
                f"({len(self.allowlist)} entries)"
            )
            return
        terminalreporter.write_sep("=", "skip allowlist", red=True, bold=True)
        for violation in self.violations:
            terminalreporter.write_line(violation, red=True)
        terminalreporter.write_line(f"every CI skip needs an issue-linked entry in {self.source}")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        OPTION,
        metavar="PATH",
        default=None,
        help="fail the run when a test skips without an issue-linked entry in PATH (CI skip budget, #2115)",
    )


def pytest_configure(config: pytest.Config) -> None:
    raw = config.getoption(OPTION)
    if raw is None:
        return
    path = Path(raw)
    if not path.is_absolute():
        path = config.invocation_params.dir / path
    try:
        allowlist = load_allowlist(path)
    except AllowlistError as exc:
        raise pytest.UsageError(str(exc)) from exc
    config.pluginmanager.register(SkipAllowlistGate(allowlist, path), "kg-skip-allowlist")
