---
name: podcast-pipeline
description: "KG podcast pipeline：從 EPUB workspace 產生腳本、TTS、字幕、QA 與終端 publish verdict；遵守 approval gates，不建立第二套工作狀態。"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Podcast pipeline workflow

這個 skill 負責 EPUB → script → audio → subtitle → QA 的 workspace workflow。15 個 stage、artifact schema、model/env 與 provenance 細節以 [`docs/sop/podcast_pipeline.md`](../../../docs/sop/podcast_pipeline.md) 為唯一技術入口。

## 觸發與邊界

使用者要建立 podcast、續跑／重跑 workspace、驗證腳本或音訊、處理 plan/script approval gate 時使用。

- 先讀 pipeline SOP 與 workspace 的 manifest／stage provenance，再決定 resume 或指定 stage。
- plan／script approval 是真正的人工 gate；未批准不得進入昂貴階段。`publish` 是終端
  stage，沒有額外 approval marker。
- QA fail、provenance drift 或輸入缺失要停止並保留 evidence，不用 `--ignore-gates` 掩蓋。
- 完整 pipeline 到達終端 `publish` 時會依 code contract 自動呼叫唯一 upload wrapper 並驗證
  catalog；credential／bucket 缺失或遠端 verify 失敗必須回報 `publish: failed`，不能把
  workspace 合成成功當成已上線。
- `podcast-publish` 只處理 pipeline 之外的明確 repair／republish／catalog reconcile，
  不與正常 pipeline 競爭另一套 publish truth。
- backend serving、production health／deploy 分別走 backend docs 或 `devops`。

## 標準路徑

1. 確認 workspace、workflow version、input fingerprint 與目前 stage。
2. 執行 SOP 指定的最小 stage range；只在有明確人工批准時越過 gate。
3. 驗證 script／audio／subtitle／QA 結果與 provenance，記錄命令、exit status、artifact hash。
4. 讀終端 publish stage 的 upload／catalog verify 結果；若只跑到 approval gate 或中途
   stage，明確標示 `publish: not run`。

## 輸出契約

回報 workspace、workflow version、完成 stage、plan/script gate、QA verdict、publish
upload／catalog verify、artifact/provenance evidence、exact HEAD 與未解 blocker。
