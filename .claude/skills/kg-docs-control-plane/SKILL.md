---
name: kg-docs-control-plane
description: "維護 docs registry、impact、metadata、generated checks 與 agent-facing surface；不保存產品工作狀態。"
user-invocable: true
version: 2.0.0
---

# Documentation control

## Authority order

1. `docs/registry.yml`：文件 ownership、trigger、source hints 與 agent-facing paths。
2. `docs/reference/*`：產品、技術、schema、host 與 feature boundaries。
3. `docs/sop/*`：可執行操作流程。
4. `docs/policy/*`：安全與不可逆邊界。
5. generated／snapshot／archive／legal：依各自 metadata 與生成契約處理。

## Standard flow

```bash
./ops/docs_impact.py --files <path...> --explain
./ops/docs_lint.sh
./ops/docs_lint.sh --registry
```

Impact 只是候選；依 registry trigger 與實際 diff 決定是否同步。文件更新與 code 同一 PR 交付，`verified_against` 必須是可達且已存在的 commit。generated entry 必須有 generator 與以自身 path 為目標的 check。

## Agent-facing surface

改 CLI、flag、env、schema、ops script、skill、workflow 或其他 agent-facing surface 時，使用 registry 的 path list 與 `--surface-scan` 證明引用已同步。不要建立第二份人工清單。

## Output

回報實際 impact command、候選文件、決定同步的文件、docs gate 結果與仍存在的 unrelated audit debt。文件沒有語義影響時明確寫 `changed docs: none`。
