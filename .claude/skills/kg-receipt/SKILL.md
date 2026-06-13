---
name: kg-receipt
description: "KG 任務收尾與交接 receipt。當使用者要求交接、handoff、總結、驗證證據、下一輪接手，或任務完成前需要固定回報格式時觸發。"
user-invocable: true
version: 1.0.0
---

# KG Receipt

本 skill 固定任務完成時留下可驗證交接。receipt 不是長文檔，不取代 commit message 或 PR body。

## Receipt Checklist

收尾前確認：

1. `git status --short` 已看過。
2. 每個宣稱完成的項目都有當下驗證 command。
3. 若改 user/agent-facing surface，已跑 docs impact/lint 或明確說明為何不需要。
4. 若改 git history / branch / worktree，已跑相應 audit。
5. 若有未跑測試，明確列原因與風險。
6. **Tooling Debt 強制表態**:`none` 或一筆。非 trivial 且未當場修 → 登 `docs/runbook/improvement_backlog.md`。撞到摩擦無聲妥協(硬幹）= 違鐵律9。

## Minimal Format

```text
Result:
- <完成的高層結果>

Changed:
- <主要改動，不逐檔流水帳>

Validation:
- <command> -> <result>

Docs/Skill Sync:
- <impact/lint result or none>

Tooling Debt:
- <small friction kept for later, or fixed with regression command>

Risk:
- <remaining risk or none>

Next:
- <只列真正需要下一輪做的事>
```

## Verification Rules

- 不說「完成」但沒有 command。
- 不用「應該可以」代替驗證。
- 不把舊輸出當本輪證據。
- 若背景工作還在跑，receipt 必須標示它不是完成證據。
- Tooling Debt 不可留空：`none` 或一筆 filed item;沉默不合法(andon · 反硬幹)。非 trivial 未當場修者登 `docs/runbook/improvement_backlog.md`,由 `platform-steward` 追到 resolved。

## Handoff Prompt Rule

若使用者要交接 prompt，必須包含：

- 目標
- repo/worktree/branch
- 已改檔案與 commit hash
- 已跑驗證命令
- 已知風險
- 下一步第一個 command
