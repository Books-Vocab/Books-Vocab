# KG Workspace Guide

KG 是 Knowledge Graph 英語學習產品：`ios/` 是 SwiftUI BooksAndVocab app，`backend/` 是 FastAPI 與官網，`lab/` 是 podcast／評估工具，`ops/` 是測試、部署與安全入口。

## GitHub-native 心智模型

GitHub 是交付控制面；本機工具只補足多 worktree 與本機驗證，不另建一套產品管理系統。

| 心智模型 | GitHub / 本機對應 | 真正 owner |
|---|---|---|
| 想做什麼、為什麼做、完成判準 | GitHub Issue | GitHub Issues |
| 優先序、視圖、里程碑 | GitHub Project | GitHub Projects |
| 一次實作的隔離環境 | branch + local worktree | Git / `ops/worktree_registry.py` |
| 變更、討論、review、驗證結果 | Pull Request | GitHub PR + review |
| 自動檢查與 required checks | GitHub Actions | `.github/workflows/` |
| 合併後的產品主幹 | `main` | GitHub protected branch |
| 發版、批准、rollback | release／部署 SOP | `ops/release.sh` + `ops/devops_kg_safe.sh` |

標準路徑：Issue → branch/worktree → commit → PR → Actions／review → merge → release。Issue、Project、PR 的狀態不在 repo 內複製；本地 registry 不存工作項目生命週期，也不決定合併。

## 本地 coordinator 的窄責任

`ops/worktree_registry.py` 只記錄本機工作樹是否被誰使用、structured Scope、thread identity、branch/path、hand-back 與驗證摘要。`ops/worktree_orchestrate.py` 只負責建立／接管 worktree、檢查 Scope overlap、執行本地 gate、保存 evidence、交回或安全移除工作樹。

GitHub 外部 ID 只作 opaque reference；Issue、Project、PR 的生命週期與合併決定都在 GitHub 完成。

## 開發規則

1. 開始前先讀本檔與對應 SoT；涉及陌生 endpoint、schema、env、release 或安全邊界，先查 `docs/registry.yml` 指向的文件。
2. 實作採 TDD：先紅、最小修復、再綠；每個獨立變更保持可 review、可回滾。
3. 分支與 worktree 要有明確 Scope；同一檔案不可被兩個 active worktree 同時認領。跨 session 協調以 registry／GitHub PR 為準，不靠聊天紀憶。
4. PR 必須讓 reviewer 能回答：改了什麼、為何改、如何驗證、是否有安全或文件影響。review 與 required checks 留在 PR；不要把它們重新寫成 repo receipt。
5. 遇到工具摩擦先修工具或記錄可重現 blocker，不以手工繞路掩蓋流程缺陷。

## 常用入口

```bash
./ops/context_route.py identify --role manager --json
./ops/context_route.py validate --json
./ops/skill_route.py validate --json
./ops/skill_route.py route --intent delivery --json
./ops/context_route.py render --role manager --intent delivery --json
./ops/worktree_registry.py list --json
./ops/worktree_orchestrate.py --help
./ops/docs_impact.py --files docs/reference/tech_index.md
./ops/docs_lint.sh
./ops/test_ops.sh worktree
```

Python 一律由 `uv` 管理；backend 測試從 `backend/` 執行 `uv run --locked python -m pytest`。iOS build/test 走 `./ops/ios_ops.sh`，不要直接拼底層命令取代既有安全入口。

## 不可省略的產品與安全邊界

- 真正產品程式碼與測試是主要資產；不要因整理交付工具而刪除它們。
- 生產操作只走 `ops/devops_kg_safe.sh`、`ops/release.sh` 與其 SOP；批准、health gate、rollback 必須保留。
- 網域、CloudKit、資料庫、felix 常駐機、App Store／TestFlight 與 backend deployment 的領域流程，以 `docs/reference/host_topology.md`、`docs/sop/deploy.md`、`docs/sop/ios.md`、`docs/sop/backup*.md` 為準。
- iOS user-facing 字串走既有 i18n lint；UI 修改先讀 `docs/sop/ui-design.md` 與對應 feature boundary。
- 文件控制面只保留 registry、impact、lint 與必要的 SoT；文件不是交付資料庫。

## 回報格式

回報只需要四件事：成果、當下驗證證據、偏離／未解 blocker、已替使用者做的決定。涉及不可逆生產動作、帳號持有人專屬批准、預算或產品策略時才停下來請示；其餘技術判斷自行完成。
