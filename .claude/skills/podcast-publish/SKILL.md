---
name: podcast-publish
description: "KG podcast publish repair workflow：對 pipeline 之外的既有 artifact 執行明確指派的 S3 republish／catalog reconcile／verify。具有外部副作用。"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Podcast publish workflow

正常 pipeline 的終端 `publish` stage 已會自動 upload + catalog verify；這個 skill 只處理
pipeline 之外的 repair、republish、cover-only reconcile 或明確的 upload verification。
upload command、S3 catalog schema、reconcile 與 rollback 細節以
[`docs/sop/podcast_pipeline.md`](../../../docs/sop/podcast_pipeline.md) 和
`ops/podcast_upload.sh` 為準。

## 觸發與邊界

只有使用者／IM 明確要求 repair、republish、catalog reconcile 或 upload verification 時
使用。pipeline 尚未完成終端 stage 時，不得用本 skill 假設它應該已發布。

- 先確認 workspace、exact HEAD、artifact hashes、QA verdict、cover／subtitle completeness 與 target catalog。
- 沒有明確 side-effect assignment、QA／artifact evidence 或 target catalog 時停在 preflight。
- 使用唯一 publish wrapper；不直接拼 `aws s3 cp/rm`，不繞過 verify，不把 local artifact 當作 public catalog 成功。
- 失敗時保留 command／exit status／remote verification，不自行清除或覆蓋既有 production asset。

## 標準路徑

1. 讀 pipeline manifest 與 publish SOP，確認所有終端 artifact 的 provenance。
2. 執行 `ops/podcast_upload.sh` 的受支持模式。
3. 驗證 S3 object、catalog index 與 client-visible metadata；任何 mismatch 都是 BLOCK。

## 輸出契約

回報 workspace、target、repair／publish mode、artifact／manifest hash、command、exit status、
remote verification、catalog result 與 rollback／retry 建議。未完成 verify 時不得回報
published／reconciled。
