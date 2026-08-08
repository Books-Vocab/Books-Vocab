---
name: kg-docs-control-plane
description: "KG 文檔控制面。當任務涉及 docs/registry.yml、docs impact、docs lint、verified_against、產品/技術索引同步、skill/doc 閉環，或改到 agent-facing/user-facing surface 時觸發。"
user-invocable: true
version: 1.0.0
---

# KG Docs Control Plane

本 skill 負責判斷文件是否該讀、該同步、該驗證。文檔是 SoT；本 skill 是流程，不複製 SoT 內容。

## Authority Order

1. `docs/registry.yml`：活文檔路由與 trigger SoT。
2. `docs/reference/*`：契約、產品面、技術索引、feature boundary。
3. `docs/sop/*`：操作流程，只有流程變更才更新。
4. `docs/policy/*`：安全政策，改動需明確理由。
5. generated/snapshot/archive/legal：依 tier 契約處理，不任意手改。

## Standard Flow

1. 改動前或改動後跑 impact：

```bash
./ops/docs_impact.py --since <base> --explain
```

若只有明確檔案清單：

```bash
./ops/docs_impact.py --files <path...> --explain
```

2. 判讀 `match_type`：

- `exact`: 優先讀並判斷是否同步。
- `suppressed-partial`: 檢查 suppressed path 是否合理。
- `broad`: 只當候選，不自動改 doc。

3. 判讀 trigger，而不是只看 path hint。
4. 若同步 docs，讓 `verified_against` 指向 **`origin/main` 可達**的 code commit（判準與不變式見 `docs/sop/doc_sync.md` 步驟 4——本地 main 刻意超前 origin，「local main 可達」不夠；`docs_lint` 對此只給帶 `origin-unreachable` token 的 WARN，不是硬閘）；doc-only 流程改動不必硬 bump unrelated reference。
5. 驗證：

```bash
./ops/docs_lint.sh
./ops/docs_lint.sh --registry
```

`--registry` 現在也會實跑每筆 `kind: generated` 的 `check:` 命令(缺 `check:` 直接 ERROR)。這是新的轉紅來源:改到 `ios/BooksAndVocab/` 或 `docs/runbook/backlog/*.json` 而沒重生對應產物,docs gate 就會紅並具名該筆 + 印出重生命令。而且 `validate_registry` 是無條件呼叫,不限 `--registry` 模式。

全 repo 健康盤點才用：

```bash
./ops/docs_lint.sh --audit
```

## Agent-Facing Surface Sync

改到 CLI subcommand、flag、env var、admin endpoint、設定 schema、ops control plane、skill 觸發語時，同一輪檢查：

```bash
rg -n "<old-command|old-flag|old-field>" .claude/skills docs/reference docs/sop docs/policy docs/runbook AGENTS.md CLAUDE.md
```

需要同步的常見落點：

- `docs/reference/tech_index.md`
- `docs/reference/product_surface.md`
- `docs/runbook/system.md`
- `.claude/skills/*/SKILL.md`
- `AGENTS.md`

## Output Contract

- `impact command`: 實際跑過的 impact/lint command
- `candidate docs`: impact 候選與判斷
- `changed docs`: 實際同步清單，沒有就寫 `none`
- `validation`: docs gate 結果
- `debt`: 既有 audit debt 與本輪是否相關
