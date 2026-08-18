---
name: kg-agent-context
description: "依 context route 載入目前 role、Issue／PR、Scope 與 domain SoT 的最小必要視野。"
---

# Agent context

先讀 `docs/reference/agent_context.md`，再執行：

```bash
./ops/context_route.py identify --role <role> --json
./ops/context_route.py validate --json
./ops/context_route.py render --role <role> --intent <intent> --json
```

## Loading discipline

- 只讀 route output 的 sources；不要預載整個 repo 或未受影響的 domain。
- GitHub Issue／PR 定義本次工作；`docs/registry.yml` 定義文件 authority；code／tests 定義實際行為。
- worktree Scope 是檔案 ownership；與 Issue acceptance、PR review、production approval 分開。
- route 不是 capability 或 permission。寫入、merge、release、deploy 仍受 GitHub rules、wrapper 與帳號權限控制。
- source 不存在、manifest 失效、Scope 不明或 live HEAD 改變時 fail closed。

## Handoff

交接只交 exact branch／path／HEAD、Scope、Issue／PR external ID、驗證命令與 blocker。不要在 repo 內另寫第二份產品狀態或優先序。
