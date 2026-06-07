"""Drift gate:business-error 謂詞(「什麼算 error」)只有一份 SoT。

admin_trends 與 ops_cli cmd_trends 都把「errors = failed pipeline + auto-judge
rejects」攤進各自的 SQL。本測試釘住兩者引用同一組 SoT 常數
(`kg.error_signals`),且 ops 不得再硬編 ``reject_reason != 'degree_cap'``
等字面 —— 任何一方私改謂詞 → 紅燈。
"""
from __future__ import annotations


def test_sot_constants_exist():
    from kg.error_signals import JUDGE_AUTO_REJECT_WHERE, PIPELINE_FAILURE_WHERE  # noqa: F401


def test_judge_reject_predicate_references_degree_cap_sot():
    """auto-judge reject 謂詞必須由 judge_log 的 DEGREE_CAP_EXCLUSION_SQL 組成,
    不得獨立硬編字面。"""
    from kg.error_signals import JUDGE_AUTO_REJECT_WHERE
    from kg.judge_log import DEGREE_CAP_EXCLUSION_SQL

    assert DEGREE_CAP_EXCLUSION_SQL in JUDGE_AUTO_REJECT_WHERE
    assert "source = 'auto'" in JUDGE_AUTO_REJECT_WHERE
    assert "accepted = 0" in JUDGE_AUTO_REJECT_WHERE


def test_admin_trends_uses_sot():
    """admin_trends 的 judge-reject extra_where 必須 == SoT 常數(同義)。"""
    import kg.error_signals as es
    import kg.admin_trends as at

    # admin_trends 應引用 SoT,不再自組字面。
    assert es.JUDGE_AUTO_REJECT_WHERE == at._JUDGE_REJECT_WHERE
    assert es.PIPELINE_FAILURE_WHERE == at._PIPELINE_FAILURE_WHERE


def test_ops_cli_uses_sot():
    """ops_cli cmd_trends 不得再出現硬編的 degree_cap 字面 —— 必須走 SoT。"""
    import inspect

    import ops_cli

    src = inspect.getsource(ops_cli.cmd_trends)
    assert "degree_cap" not in src, "ops_cli 仍硬編 degree_cap 字面,未走 error_signals SoT"
    assert "status = 'failed'" not in src, "ops_cli 仍硬編 pipeline failure 字面"
