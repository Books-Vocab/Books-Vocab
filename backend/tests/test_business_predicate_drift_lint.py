"""Drift 護欄(判準 #3 自我執行版):複合業務謂詞的 SQL 字面只准住在其 SoT 模組。

parity 測試擋「現有兩面分歧」;本 lint 擋「**未來**新消費端又硬編字面」——
正是 admin_observability / observability_alerts 變成第三處 drift 才被抓到的那種洩漏。
任何人在 SoT 以外的 src/ops 檔重新貼上受管謂詞 → 紅燈,逼其改引用 SoT 常數。

只守「複合 + 曾經 drift」的謂詞;`source = 'auto'` / `accepted = 0` 這類正當共用
的單欄詞彙不守(不同 query 形狀會合理重複,守了會誤報)。

**比對採空白正規化**:`status='failed'`(無空格)與 `status = 'failed'` 視為同一個
受管字面 —— 之前用 byte-exact 比對才讓 admin_observability 的無空格寫法溜過去。
保留單引號要求:SQL 字串字面慣用單引號,不正規化引號,以免誤報 Python 的
`status = "failed"` 賦值(admin_test_matrix/results.py、runner.py kwarg 等無關碼)。
"""
from __future__ import annotations

import re
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
_SRC = _BACKEND / "src" / "kg"


def _norm(s: str) -> str:
    """去除所有空白,讓 `a = 'x'` / `a='x'` / `a =  'x'` 正規化為同一形。"""
    return re.sub(r"\s+", "", s)


# 受管謂詞(canonical 形)→ 唯一允許出現的 SoT owner 檔名。
# 兩者都是先前真實 drift 過的複合業務謂詞片段。
_GUARDS: dict[str, str] = {
    # auto-judge reject 的 degree_cap 排除:SoT = judge_log.DEGREE_CAP_EXCLUSION_SQL
    "reject_reason != 'degree_cap'": "judge_log.py",
    # pipeline 業務失敗:SoT = error_signals.PIPELINE_FAILURE_WHERE
    "status = 'failed'": "error_signals.py",
}


def _scanned_files() -> list[Path]:
    """src/kg 全樹 + 所有 top-level ops_*.py / *_cli.py(自動發現,不寫死清單)。"""
    seen: dict[Path, None] = {}
    for p in _SRC.rglob("*.py"):
        if "__pycache__" not in p.parts:
            seen[p] = None
    for pattern in ("ops_*.py", "*_cli.py"):
        for p in _BACKEND.glob(pattern):
            seen[p] = None
    return [p for p in seen if p.exists()]


def test_guarded_predicates_live_only_in_their_sot():
    violations: list[str] = []
    for path in _scanned_files():
        text = _norm(path.read_text(encoding="utf-8"))
        for literal, owner in _GUARDS.items():
            if _norm(literal) in text and path.name != owner:
                rel = path.relative_to(_BACKEND)
                violations.append(
                    f"{rel} 硬編受管謂詞 {literal!r}(空白不敏感);該謂詞 SoT 在 "
                    f"{owner},請改引用其常數而非貼字面"
                )
    assert not violations, "業務謂詞 drift:\n" + "\n".join(violations)


def test_guard_owners_actually_embody_their_literal():
    """防護自身有效性:每個 SoT 常數的**執行期值**必須仍體現受管謂詞。

    以 runtime 值(而非 source 字面)比對 —— owner 可用 f-string 組裝常數,
    source 不一定含原字面,但組出來的值必須仍是該謂詞,否則 typo / 漏 clause
    會悄悄改掉「什麼算 error」而本 lint 與 parity 都抓不到。
    """
    from kg.error_signals import PIPELINE_FAILURE_WHERE
    from kg.judge_log import DEGREE_CAP_EXCLUSION_SQL

    runtime = {
        "status = 'failed'": PIPELINE_FAILURE_WHERE,
        "reject_reason != 'degree_cap'": DEGREE_CAP_EXCLUSION_SQL,
    }
    for literal, value in runtime.items():
        assert _norm(literal) in _norm(value), (
            f"SoT 常數值 {value!r} 不再體現受管謂詞 {literal!r} —— "
            f"謂詞可能被悄改,請同步 _GUARDS 與消費端"
        )
