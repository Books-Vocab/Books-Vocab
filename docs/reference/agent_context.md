<!-- doc-meta
tier: reference
authority: SoT
update_trigger: agent_context_changed
scope:
  - CLAUDE.md
  - docs/reference/project_onboarding.md
  - docs/reference/delivery_model.md
  - .claude/agents/
  - .claude/skills/
  - docs/registry.yml
  - ops/context_plane.json
  - ops/context_route.py
  - ops/skill_route.py
  - ops/agent_onboard.py
verified_against: 8ec4780950c73b6006649c5c08e69c05962abfc1
-->

# Agent Context Index

這份文件只定義「如何把正確的上下文交給正確身份的代理」。專案概覽與角色邊界不在此重複：先讀 [`project_onboarding.md`](project_onboarding.md)，交付角色與兩條工作路徑以 [`delivery_model.md`](delivery_model.md) 為準，技術細節由 `docs/registry.yml` 導航。

## 強制冷啟動順序

代理不能直接跳到 specialist skill 或 domain 文件。已知身份、工作意圖與入口後，先執行：

```bash
./ops/agent_onboard.py \
  --identity '<canonical identity or alias>' \
  --intent '<delivery|review|docs|release|backend|ios>' \
  --entry '<coordination|merge|direct-assignment|issue|pr-review|release>' \
  --specialist-intent '<optional identity-scoped specialist intent>' \
  --evidence '<JSON object containing the required assignment evidence>' \
  --json
```

依 `kg.agent_onboarding.v2` 的 `load_order` 嚴格載入：

1. **project**：`docs/reference/project_onboarding.md`，了解 KG 產品地圖、GitHub-native 控制面與本地 coordinator 邊界。
2. **identity**：由 `ops/context_plane.json` 的 canonical identity 確認責任與 `not_owns`；執行層 mapping 只供 loader 維持相容，不是 agent-facing 角色模型。
3. **assignment**：確認 User／IM direct assignment、GitHub Issue 或 GitHub PR，並取得 acceptance、exact HEAD 與 structured Scope。
4. **skill**：使用 onboarding kernel route 指定的唯一 primary skill、required dependencies、forbidden skills；若有 `specialist-intent`，它會取代 generic high-level route，不能自行把兩條 route 拼在一起。
5. **domain**：只讀本次 intent 的 bounded sources，完成測試、review、docs impact 或安全 SOP。

`status != ready`（包括缺少 evidence 時的 `awaiting-assignment`）、source 不存在、identity／intent／entry 不匹配、context 與 skill primary 不一致時，必須停在 onboarding；不可用預設值猜測或繼續載入。

`specialist-intent` 不是自由字串：它必須由 `ops/context_plane.json` 對該 identity／intent／entry 明確列入白名單，並由 `.claude/skills/catalog.json` 解析成唯一 primary 與 dependencies。未指定時使用 generic route；指定後只讀 effective route，不能自行疊加另一個 specialist。

## Canonical identity

canonical identity 的完整責任定義只保留在 [`delivery_model.md`](delivery_model.md) 與 `ops/context_plane.json`：

| identity | 入口／工作重點 |
|---|---|
| CM／IM | codebase 收斂，或 GitHub Issue 收件、排序與派工 |
| Worker／Issue Solver | direct assignment 或 GitHub Issue → branch/worktree → PR |
| CR | PR diff、fresh checks 與 review 結論 |
| DS | docs impact、registry／SoT 與 docs lint |
| Release operator | 已批准的 release/deploy/rollback SOP |

CLI 仍接受既有相容 alias，但 alias 只存在於
`context_plane.json`／`context_route.py` 的執行層；代理、人類文件與 assignment
一律使用上表的 canonical identity。這個 mapping 不新增角色，也不授予權限。
GitHub rules、Actions environment、production wrapper 與帳號權限才是授權來源。

## SoT 導航

| 問題 | 先讀 |
|---|---|
| KG 產品地圖與共同安全規則 | `docs/reference/project_onboarding.md` |
| 角色、兩條入口、PR 收斂與本地 coordinator 邊界 | `docs/reference/delivery_model.md` |
| endpoint、模組、env、domain 技術細節 | `docs/reference/product_surface.md`、`docs/reference/tech_index.md` |
| 文件 owner、trigger、impact | `docs/registry.yml`、`./ops/docs_impact.py` |
| worktree ownership、Scope、thread 與 hand-back | `ops/worktree_registry.py`、`ops/lib/worktree_scope.py` |
| CI／PR checks | `.github/workflows/`、`docs/sop/review_discipline.md` |
| release、deploy、批准與 rollback | `docs/sop/release.md`、`docs/sop/deploy.md`、`docs/policy/safety.md` |
| iOS UI／Simulator | `docs/sop/ui-design.md`、對應 feature boundary、iOS verification skill |

## Route output contract

`context_route.py` 是必須帶 `--diagnostic` 的 maintainer-only bounded navigation，不是 agent loader、merge queue、GitHub API 或 permission system。成功輸出必須包含：

- `status`、`role`、`identity_ids`、`intent`、`skill`、`skill_intent`。
- `onboarding`、`load_order` 與去重後的 `sources`。
- `next_action` 與 `authority.granted == false`。

`skill_route.py` 再提供唯一 `primary`、selected skills 與 typed `dependencies`，也只供 maintainer diagnostic 使用。context intent 到 skill intent 的 mapping 必須在 manifest 中明確登錄，不能由代理自行猜測。

## Assignment、Scope 與證據

Scope 是本機檔案 ownership 與 collision 判定，不是需求或權限。Issue work 的目標、優先序與 acceptance 在 GitHub Issue；direct assignment 的目標與 acceptance 在 assignment／PR；PR 的 diff、checks、review 與驗證證據是交付真相。

最小交接證據包含 Issue／PR opaque ID（若已有）、direct assignment 摘要（若無 Issue）、branch、worktree path、exact HEAD、Scope、命令與 exit status、未解 blocker。交接證據不取代 GitHub PR，也不改變 merge／release 授權。
