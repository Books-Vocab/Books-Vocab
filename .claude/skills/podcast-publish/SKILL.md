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
`ops/podcast_cover_publish.py`、`ops/podcast_preview_backfill.py`、`ops/podcast_upload.sh` 為準。

## 觸發與邊界

只有使用者／IM 明確要求 repair、republish、catalog reconcile 或 upload verification 時
使用。pipeline 尚未完成終端 stage 時，不得用本 skill 假設它應該已發布。

- 先確認 workspace、exact HEAD、artifact hashes、QA verdict、cover／subtitle completeness 與 target catalog。
- 沒有明確 side-effect assignment、QA／artifact evidence 或 target catalog 時停在 preflight。
- 依模式選 wrapper，不直接拼 `aws s3 cp/rm`，不繞過 verify，不把 local artifact 當作 public catalog 成功：
  - cover-only／metadata-only repair：`uv run --no-project --with boto3 python ops/podcast_cover_publish.py ... [--check|--execute]`，先 dry-run／`--check` 再 `--execute`。
  - preview 回填：`ops/podcast_preview_backfill.py`。
  - `ops/podcast_upload.sh` 只用於完整 republish，且 local workspace 必須持有每一集；先跑 `--dry-run`。它從 local audio 重組 staging 並 prune S3 remote keys，local 與 S3 不同步時會丟 episode 或誤刪 audio。
  - **部分重發（只重合成部分集數、其餘 mp3 只存在 S3）必須用 `ops/podcast_upload.sh <ws> --only-episodes 1,3,7 [--dry-run]`**（蘊含 `--no-prune`）：只上傳點名集數的 audio／preview／字幕／script，不發任何 delete；metadata.json 與既有 remote metadata 合併，未點名集數保留 remote 條目，index 照常重建。需要既有 remote metadata；點名集數 local 缺檔即中止。`--no-prune` 單用＝完整上傳但不 prune。
- 失敗時保留 command／exit status／remote verification，不自行清除或覆蓋既有 production asset。

## 標準路徑

1. 讀 pipeline manifest 與 publish SOP，確認所有終端 artifact 的 provenance。
2. 依模式選 wrapper（與 SOP 一致）：cover-only／metadata-only 走 `ops/podcast_cover_publish.py`（dry-run 後 `--execute`）；preview 回填走 `ops/podcast_preview_backfill.py`；完整 republish 且 local workspace 持有每一集時才用 `ops/podcast_upload.sh`（先 `--dry-run`，注意會 prune S3）；只重發部分集數時一律加 `--only-episodes`，不得跑預設模式。
3. 驗證 S3 object、catalog index 與 client-visible metadata；任何 mismatch 都是 BLOCK。

## 輸出契約

回報 workspace、target、repair／publish mode、artifact／manifest hash、command、exit status、
remote verification、catalog result 與 rollback／retry 建議。未完成 verify 時不得回報
published／reconciled。
