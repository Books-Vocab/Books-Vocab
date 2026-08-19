---
name: devops
description: "KG backend production operations：健康檢查、狀態／日誌、用戶與資料操作、部署安全與 rollback 路由。只在需要實際 production surface 或 remote ops 時使用；成本分析走 billing，podcast pipeline／publish 走對應 podcast skills，App Store release 走 source-command-release。"
allowed-tools: Bash, Read, Grep
---

# KG production operations

這個 skill 是 production／remote operation 的選路與安全邊界，不是 command encyclopedia。詳細命令、host topology、資料 schema 與事故處理只從下列 SoT 載入，避免把過期的 wrapper 速查表當成現況：

- `docs/reference/host_topology.md`：現役 standby、Cloudflare Tunnel、rollback host 與資料位置。
- `docs/sop/debug.md`：status、health、logs、502、資源與資料診斷。
- `docs/sop/deploy.md`：deploy、migration、env、reconciler、rollback。
- `docs/sop/backup.md`、`docs/sop/backup_restore.md`：backup freshness、restore 與 disaster recovery。
- `docs/reference/ops_state_plane.md`：`ops-cli`／`ops-edit` 的產品狀態與 round-trip 契約。
- `docs/policy/safety.md`：不可逆操作與批准邊界。

## Route by operation

| 使用者要做什麼 | 先讀 | 允許的第一步 |
|---|---|---|
| 查服務是否健康、502、container、資源、日誌 | `debug.md` + `host_topology.md` | `./ops/devops_kg_safe.sh health --json` 或 typed read-only command |
| 查／修某個 user、vocab、graph、quota 或 state projection | `ops_state_plane.md` + backend／backup SOP | 先用 typed read-only `ops-cli`，寫入只走 `ops-edit` dry-run |
| deploy、migration、backup、rollback | `deploy.md` + `backup_restore.md` + `safety.md` | `./ops/devops_kg_safe.sh preflight`，再依 SOP dry-run |
| 只做成本盤點或 bundle 建議 | `.claude/skills/billing/SKILL.md` | 不切入 devops mutation |
| EPUB→TTS→字幕→S3 podcast | `.claude/skills/podcast-pipeline/`, `.claude/skills/podcast-publish/` + `docs/sop/podcast_pipeline.md` | 不使用 backend devops wrapper 代替 podcast ops |
| iOS archive／TestFlight／App Store | `source-command-release` + `docs/sop/ios.md` | 不用 devops 取代 release gate |

### ops-cli 子指令

`ops-cli` 是讀取產品狀態的 typed surface；先選這裡的子指令，不手寫 `db-query` SQL。

```bash
ops-cli user-quota <uid>                              # 24h 額度與逐時明細
ops-cli user-stats <uid>                              # 單字庫統計
ops-cli user-config <uid>                             # 唯讀 user config
ops-cli world-state <uid>                             # cards/notebooks/graphs/config 投影
ops-cli world-export <uid> [--out <path>]             # 匯出 ops-edit seed 相容 spec
ops-cli world-diff <uid> <spec.json>                  # 比對 expectation 或 seed spec
ops-cli quota-overview                                # 全用戶 24h 額度總覽
ops-cli active-users [hours]                          # 近 N 小時活躍用戶
ops-cli card-find <uid> <substring>                   # 搜尋 card.content
ops-cli card-get <uid> <id|content>                   # 取得單卡完整資料
ops-cli db-query <uid> SQL...                         # 受限唯讀 SQL；無 typed command 時才使用
ops-cli analyze <uid> [level]                         # 圖譜、連結品質、embedding、異常分析
ops-cli cost <uid> [--range R]                        # 單用戶 cost-by-call_type
ops-cli fleet-overview                                # 跨用戶 cards/links/月 cost 總覽
ops-cli cost-overview [--range R]                     # 全用戶 cost 排名
ops-cli sync-trace <uid> [--date YYYY-MM-DD]          # 用戶 sync 時間線
ops-cli timeseries <metric> [--bucket day|week|month] [--range R] [--uid all|<uid>] [--fill-zero]
ops-cli trends [--window N]                           # 全域 errors/active/tokens 趨勢
ops-cli llm-errors [--window N] [--uid all|<uid>]     # LLM 429/5xx/timeout 監控
ops-cli dictionary-health [--window <hours>]          # 字典 provider/cache 健康
```

## Safety contract

1. 先確認 host、repo、branch、exact HEAD、目的與是否 production。
2. 所有 production 操作先跑 `preflight`；deploy／migration 前依 SOP 做 backup；任何 mutation 先 dry-run。
3. 只使用 `ops/devops_kg_safe.sh` 的 typed surface 與既有 SOP；不自行組 ssh、docker、SQL 或破壞性 cloud command 取代 wrapper。
4. `status=ready` 只代表 onboarding evidence 齊全，不代表 production authorization。沒有明確批准、target、rollback candidate、health gate 時停止在可驗證的 read-only／dry-run。
5. 不刪除資料、container volume、backup 或 user；不把 WARN、timeout、stale deployment drift 或 baseline failure 報成健康。

## Minimal evidence

回報必須包含：operation、host／target、branch／exact HEAD（若涉及 checkout）、實際命令與 exit status、JSON／log／health 證據、是否寫入、deviation／rollback path，以及下一個需要的批准或安全動作。健康命令成功不等於 release 或 deployment 成功；發布另走 `source-command-release`。
