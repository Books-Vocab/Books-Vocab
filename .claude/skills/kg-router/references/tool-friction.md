# Tool Friction

只有當 typed task 是 `tool-friction`，或目前使用 typed tool 遇到摩擦時才載入本節；一般冷啟動與
domain route 不得預載。

使用 typed tool 遇到摩擦時先判斷嚴重度：

- 小問題：不影響正確性、不會誘導繞路，例如文案可更清楚。記到 receipt 的 `tooling debt`，回到原目標。
- 中大型問題：help 失準、入口漂移、JSON 不穩、錯誤訊息不可行動、工具讓 agent 想繞過 typed surface。
  立即停下來修工具／skill／doc，跑對應 regression，再回到原目標。
- 生產或資料寫入路徑上的摩擦預設視為中大型問題。

非當場修掉者一律立單，但立單前先查重：

```bash
./ops/backlog.py list --grep '<關鍵字或檔名>'
```

命中就接手既有票；沒有命中才用 `./ops/backlog.py add`。`list --grep` 掃 detail／resolution／plan／fix_site，
並與其他旗標取交集，不要把全表 `list` 當 dispatch queue。自由文字含反引號、`$` 或跳脫字元時，改用
`--<flag>-file <路徑>`，避免 shell 先改寫 argv。能一句話講清楚就補 `--brief` 與 `--scope`。

批次 wave worker 必須用 `add --stage`，讓整合者以 `anchor --commit` 落地；一般單線工作才用裸 `add`。

票的角色邊界、狀態與情境一律讀 `./ops/backlog.py lifecycle --json`；router 不另造流程版本。

- `--stream IMP` → owner `platform-steward`
- `--stream APP` → owner 對應 Line worker（`ios-engineer`／`backend-engineer`），取票用
  `./ops/backlog.py dispatch --stream APP`，不要用 `list --stream APP`（後者會吐出已結案與已認領票）。

嚴重度（小／中大）與 stream（誰是 owner）是兩個獨立判定，不可混用；完整分流判準由 `kg-receipt`
的「Stream 分流」負責。
