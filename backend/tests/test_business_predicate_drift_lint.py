"""Drift 護欄(判準 #3 自我執行版):複合業務謂詞的 SQL 字面只准住在其 SoT 模組。

parity 測試擋「現有兩面分歧」;本 lint 擋「**未來**新消費端又硬編字面」——
正是這次 observability_alerts 變成第三處 drift 才被抓到的那種洩漏。任何人在
SoT 以外的 src 檔重新貼上受管字面 → 紅燈,逼其改引用 SoT 常數。

只守「複合 + 曾經 drift」的字面;`source = 'auto'` / `accepted = 0` 這類正當共用
的單欄詞彙不守(不同 query 形狀會合理重複,守了會誤報)。
"""
from __future__ import annotations

from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
_SRC = _BACKEND / "src" / "kg"

# 受管字面 → 唯一允許出現的檔名(SoT owner)。
# 兩者都是先前真實 drift 過的複合業務謂詞片段。
_GUARDS: dict[str, str] = {
    # auto-judge reject 的 degree_cap 排除:SoT = judge_log.DEGREE_CAP_EXCLUSION_SQL
    "reject_reason != 'degree_cap'": "judge_log.py",
    # pipeline 業務失敗:SoT = error_signals.PIPELINE_FAILURE_WHERE
    "status = 'failed'": "error_signals.py",
}


def _scanned_files() -> list[Path]:
    files = [p for p in _SRC.rglob("*.py") if "__pycache__" not in p.parts]
    files += [_BACKEND / "ops_cli.py", _BACKEND / "ops_edit.py"]
    return [p for p in files if p.exists()]


def test_guarded_predicates_live_only_in_their_sot():
    violations: list[str] = []
    for path in _scanned_files():
        text = path.read_text(encoding="utf-8")
        for literal, owner in _GUARDS.items():
            if literal in text and path.name != owner:
                rel = path.relative_to(_BACKEND)
                violations.append(
                    f"{rel} 硬編受管字面 {literal!r};該謂詞 SoT 在 {owner},"
                    f"請改引用其常數而非貼字面"
                )
    assert not violations, "業務謂詞 drift:\n" + "\n".join(violations)


def test_guard_owners_actually_contain_their_literal():
    """防護自身有效性:每個 owner 必須真的還持有該字面(SoT 沒被改名/搬走)。"""
    for literal, owner in _GUARDS.items():
        owner_path = _SRC / owner
        assert owner_path.exists(), f"SoT owner 不存在:{owner}"
        assert literal in owner_path.read_text(encoding="utf-8"), (
            f"{owner} 不再持有 {literal!r} —— SoT 可能已搬移,請更新 _GUARDS"
        )
