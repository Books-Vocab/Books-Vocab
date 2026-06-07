"""Business-error 訊號謂詞 —— 「什麼算 error」的單一真相源。

站台級監控(admin_trends / ops_cli trends)把錯誤定義為:
  errors = failed pipeline_runs  +  auto-judge rejects

這兩條 WHERE 謂詞過去在 admin 與 ops 各寫一份(ops 還把 judge 的
degree_cap 排除字面硬編,與 judge_log 的 SoT 常數脫鉤而靜默 drift)。本模組
集中為命名常數,admin(RW)與 ops(connect_ro)各自只負責連線,共用同一謂詞。

純字串字面,不開連線、不依賴 DATA_DIR,可安全被任一面 import。
"""
from __future__ import annotations

from .judge_log import DEGREE_CAP_EXCLUSION_SQL

# pipeline_runs 終態失敗 = 一次業務錯誤。
# STATUS 是裸狀態值(與 pipeline_log end_run 寫入端一致),供 IN 清單/CASE 等
# 非 WHERE 形狀的 query 重用;WHERE 片段由其組成,兩者永不分歧。
PIPELINE_FAILURE_STATUS = "failed"
PIPELINE_FAILURE_WHERE = f"status = '{PIPELINE_FAILURE_STATUS}'"

# auto-judge 拒絕 = 一次業務錯誤,但排除 degree_cap(容量保護,非品質問題)。
# 拆成原子謂詞:不同 query 形狀(WHERE 串接 / CASE WHEN 計數)組合同一組 SoT。
# degree_cap 排除沿用 judge_log 的 SoT 常數,改一處即同步所有消費面。
JUDGE_AUTO_SOURCE_WHERE = "source = 'auto'"
JUDGE_REJECTED_WHERE = "accepted = 0"
JUDGE_AUTO_REJECT_WHERE = (
    f"{JUDGE_AUTO_SOURCE_WHERE} AND {JUDGE_REJECTED_WHERE} AND {DEGREE_CAP_EXCLUSION_SQL}"
)
