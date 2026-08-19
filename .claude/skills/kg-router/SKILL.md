---
name: kg-router
description: "KG agent onboarding kernel：先確認 canonical identity、assignment evidence 與 bounded route，再載入唯一 primary skill 和 domain sources。"
---

# KG onboarding and route kernel

這是所有 agent 共用的唯一冷啟動 skill。它只負責把「人／工作／入口」轉成可驗證的 project → identity → assignment → skill → domain route；不代替 GitHub、PR、worktree、release 或 production 授權。

## Mandatory entry

從 caller、User／IM assignment 或 GitHub Issue／PR 取得 canonical identity、intent、entry 與外部 evidence；缺一不可自行猜測。執行：

```bash
./ops/agent_onboard.py \
  --identity '<identity>' \
  --intent '<intent>' \
  --entry '<entry>' \
  --specialist-intent '<optional identity-scoped specialist intent>' \
  --evidence '<JSON object containing the required assignment evidence>' \
  --json
```

- `status=awaiting-assignment`：缺少 required evidence；停在 assignment，不讀 specialist 或 domain。
- `status=ready`：只按輸出的 `load_order` 讀取，不能自行增加 skill 或文件；若指定 `specialist-intent`，它是有效 primary route，取代該高階 intent 的 generic skill route。
- 其他錯誤：manifest、identity、entry、source 或 route contract 失效，fail closed。

## Loading order

1. **project**：讀 `docs/reference/project_onboarding.md`，建立 KG 產品地圖、GitHub control plane 與 local coordinator 邊界。
2. **identity**：讀 route 指定的 canonical 責任與 `not_owns`；不要自行拼角色或權限。
3. **assignment**：確認 Issue／PR 或 direct assignment、acceptance、exact HEAD 與 structured Scope；Scope 是本機檔案 ownership，不是授權。
4. **skill**：依 route 先載入本 skill，再載入唯一 `primary` 與 required dependencies；`specialist-intent` 必須在 identity／intent／entry 白名單內，forbidden skill 不得讀取。
5. **domain**：只讀 `domain_sources`、受影響 SoT 與 assignment／PR，不預載整個 repo。

## Authority boundaries

- GitHub Issue／Project／PR／Actions／`main` 是交付真相；本地 coordinator 只保護 worktree ownership、Scope、驗證與 hand-back。
- route 只是 navigation。它不授予 GitHub API、merge、release、deploy、帳號或 production 寫入權限。
- code／tests 定義產品行為；`docs/registry.yml` 定義文件 authority／impact；domain SOP 定義不可逆操作。
- hand-back 是本機 evidence，不是 mergeability、release readiness 或 production approval。

## Maintainer-only contract checks

通常由 `agent_onboard.py` 完成；只有診斷 route contract 時才單獨執行：

```bash
./ops/context_route.py validate --json
./ops/skill_route.py validate --json
./ops/skill_route.py route --diagnostic --intent <canonical-skill-intent> --json
```

成功回報至少包含 canonical identity、intent、entry、primary skill、required dependencies、domain sources、next action、exact HEAD／Scope 與 `authority.granted=false`。任何 stale evidence、WARN、timeout、baseline failure 或 missing permission 都原樣回報，不能轉成 PASS。
