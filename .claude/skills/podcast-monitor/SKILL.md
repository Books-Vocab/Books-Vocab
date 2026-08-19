---
name: podcast-monitor
description: "KG podcast workspace 與 dashboard 的唯讀監控／診斷：判斷 stage、approval、artifact、QA 或 upload 狀態，不修改 workspace 或 production。"
allowed-tools: Bash, Read, Glob, Grep
---

# Podcast monitoring workflow

這個 skill 只做 podcast pipeline 的唯讀觀測與診斷。狀態、stage marker、provenance、dashboard API 與錯誤分類以 [`docs/sop/podcast_pipeline.md`](../../../docs/sop/podcast_pipeline.md) 為技術來源。

## 觸發與邊界

使用者要查 workspace 進度、pipeline 是否卡住、哪個 gate 等待、QA／artifact／upload verification 為何失敗時使用。

- 只讀 workspace manifest、stage markers、provenance、logs 與 dashboard 狀態。
- 不重跑 stage、不建立或修改 approval marker、不發布、不刪除 artifact。
- 若需要修復或續跑，交給 `podcast-pipeline`；若需要外部 publish，交給 `podcast-publish`。

## 診斷順序

1. 確認 workspace identity、workflow version 與目前 HEAD／input provenance。
2. 找第一個未完成或 drift 的 stage，區分 `awaiting approval`、`failed`、`missing artifact`、`verification mismatch`。
3. 只引用實際 log／marker／hash；不可把 dashboard 的 stale 狀態當成成功。

## 輸出契約

回報 workspace、目前 stage、狀態分類、最小證據（marker／log／hash）、是否需要 pipeline 或 publish hand-off；所有副作用欄位固定標示 `not run`。
