---
name: kg-router
description: "KG 冷啟動與任務路由：確認 CM／IM／Worker／Issue Solver／CR／DS context、Issue／PR 範圍、SoT、skill 與安全邊界。"
---

# KG router

## Cold start

1. 先讀 `docs/reference/delivery_model.md`，確認工作是 Worker direct assignment 還是 Issue Solver flow；再確認 cwd、repo、branch、HEAD 與 dirty state。
2. 唯讀確認 context role：`./ops/context_route.py identify --role manager --json`（實際 role 依 caller）。
3. 驗證 skill catalog：`./ops/skill_route.py validate --json`。
4. 依 typed intent 選一個 primary skill：`./ops/skill_route.py route --intent <intent> --json`。
5. 用 `./ops/context_route.py render --role <role> --intent <intent> --json` 取得 bounded sources。
6. 讀對應的 GitHub Issue（若有）、PR 與 SoT；再決定是否需要 worktree、production 或外部工具。

## Routing table

| 問題 | 入口 |
|---|---|
| context role／sources | `ops/context_route.py`、`docs/reference/agent_context.md` |
| skill primary／dependencies | `ops/skill_route.py`、`.claude/skills/catalog.json` |
| product existence | `docs/reference/product_surface.md` |
| technical entrypoint | `docs/reference/tech_index.md` |
| document impact | `ops/docs_impact.py`、`docs/registry.yml` |
| local worktree | `worktree-flow`、`ops/worktree_orchestrate.py` |
| production／release | `devops`／`source-command-release` 與 domain SOP |

## Hard stops

- Route output 只是導航，不是 GitHub、帳號或 production 授權。
- 沒有 Issue／PR 目標，且 direct assignment 也沒有具名範圍與 acceptance 時，不開始跨檔修改。
- 不讀整個 repo 來代替 targeted authority lookup。
- 遇到不可逆 production、帳號持有人批准、預算或策略選擇才升級；其餘技術判斷自行完成。
- 長操作必須可見；失敗、timeout、stale evidence 與 missing permission 都是偏離。

## Output contract

路由完成後回報 role、intent、primary skill、sources、next action 與 capability／permission 仍未授權的事實。若路由缺 source 或 manifest 無效，fail closed。
