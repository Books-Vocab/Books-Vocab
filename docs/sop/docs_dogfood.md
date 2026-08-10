<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - docs/
  - ops/docs_impact.py
  - ops/docs_lint.sh
verified_against: b3bc9b1fa
-->
# Docs Dogfood SOP

目的:用「下一個 agent 能不能低成本做對」驗證文檔系統,不是驗證作者意圖。dogfood agent 只做讀取、推理、命令驗證與報告,不改檔。

## 測試任務

每個 agent 選一個角色執行:

| 角色 | 任務 | 必查入口 |
|---|---|---|
| backend-change | 假設要改 `backend/src/kg/routers/vocab.py`,判斷需同步哪些 docs | `docs/registry.yml`, `ops/docs_impact.py`, `docs/reference/tech_index.md`, `docs/sop/doc_sync.md` |
| ops-change | 假設要改 `ops/devops_kg_safe.sh`,判斷 docs gate 會提示什麼,哪些提示是必要/噪音 | `docs/registry.yml`, `ops/docs_impact.py`, `docs/policy/safety.md`, `docs/sop/deploy.md`, `docs/sop/debug.md` |
| docs-tooling-change | 假設要改 `ops/docs_lint.sh`,判斷 impact hints 是否足夠精準,必要時用 `--explain` 追噪音/漏報來源；若涉及 feature-boundary 規則,驗證 LOC 欄的紅綠合成案例 | `ops/docs_impact.py`, `docs/registry.yml`, `docs/sop/doc_sync.md`, `ops/tests/test_feature_boundary_loc_lint.sh` |
| ios-feature-change | 假設要改 `ios/BooksAndVocab/Models/Book.swift`,判斷該查哪些 feature boundary / snapshot | `docs/registry.yml`, `docs/reference/tech_index.md`, `docs/reference/feature_boundary/bookshelf.md` |
| maintenance | 只看文檔系統本身,判斷新 agent 如何知道該跑哪些 gate；先走 docs-first 入口,必要時才 deep dive | `CLAUDE.md`, `docs/registry.yml`, `docs/sop/doc_sync.md`（必要時再看 `.github/PULL_REQUEST_TEMPLATE.md`, `ops/tests/test_docs_lint.sh`） |

## 必跑命令

依角色至少跑一個 `docs_impact.py --files ...` 樣本,並跑:

```bash
./ops/docs_lint.sh
./ops/docs_lint.sh --registry
./ops/docs_lint.sh --audit
./ops/docs_registry_coverage.py
```

`docs_impact.py --files ...` 是假設單一檔案改動時的精準樣本；需要理解某份 doc 為何被 broad source 命中後又被 `!path` / `!glob` 排除時,補跑 `--explain`。輸出上的 `match_type=exact|broad|suppressed-partial|suppressed` 是第一層理由欄位：先看它再決定要不要下鑽 registry。若某份 doc 仍有有效 impact,但其中一部分路徑被 suppression 壓掉,同一行 `IMPACT` 也會帶 `excluded_changed=` / `excluded_by=`。`./ops/docs_lint.sh` 反映目前 checkout 內所有 range / staged / unstaged / untracked 變更,會包含 dogfood branch 自身正在改的檔案；當它印出 registry impact hints 時,現在也會直接附 `./ops/docs_impact.py --since <base> --explain` follow-up，並明說下方 frontmatter checks 只覆蓋目前 checkout 裡有變更的 docs、non-doc 變更要以上方 impact hints 判讀。若這次完全沒有 docs 被選進 lint,它也會直說。`docs/reference/feature_boundary/*.md` 的表格不承載手寫 LOC；docs-tooling dogfood 需用 `ops/tests/test_feature_boundary_loc_lint.sh` 確認含 `檔案 | 行數 | 說明` 或 Swift 路徑後 LOC 的案例被拒絕,僅保留檔案/責任描述與一般數字內容的案例通過。`./ops/docs_registry_coverage.py` 的 human output 則以 active/backlog 兩層為主，backlog 只屬資訊,不要把它誤讀成日常 gate debt。回報時要分開判讀,不要把 default gate 的 ambient hints 當成該角色假設檔案的唯一結果。

## 回報格式

回報必須使用下列格式:

```text
role: <role>
task_result: pass | partial | fail
time_to_first_authoritative_doc: <short estimate>
commands:
- <command> => <rc/result summary>
findings:
- severity: block | fix | noise | nit
  evidence: <file/command output>
  issue: <concrete issue>
  suggested_change: <specific docs/script/registry change>
missing_links:
- <what was hard to find, or none>
confidence: high | medium | low
```

## 判準

- **pass**:能在 10 分鐘內定位權威 docs、跑對 gate、辨識 doc-sync 範圍,且沒有 block/fix 級問題。
- **partial**:能完成任務,但有噪音、入口不明、命令輸出需要人工猜測。
- **fail**:找不到權威 docs、gate 輸出誤導、或文檔之間互相矛盾。

dogfood 結果要彙整成「問題 → 證據 → 修法 → 優先級」,再決定是否修改 registry/docs/script。
