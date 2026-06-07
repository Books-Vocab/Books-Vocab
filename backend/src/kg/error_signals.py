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
PIPELINE_FAILURE_WHERE = "status = 'failed'"

# auto-judge 拒絕 = 一次業務錯誤,但排除 degree_cap(容量保護,非品質問題)。
# degree_cap 排除沿用 judge_log 的 SoT 常數,改一處即同步兩面。
JUDGE_AUTO_REJECT_WHERE = f"source = 'auto' AND accepted = 0 AND {DEGREE_CAP_EXCLUSION_SQL}"
