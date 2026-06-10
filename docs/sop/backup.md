<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - ops/
  - backend/data
verified_against: f0d37ca4
-->
# Backup 策略總覽

KG 用**三層 backup**互相補位。各層獨立,單一層失效不阻擋整體還原。事故 SOP 走 `docs/sop/backup_restore.md`。

| 層 | 工具 | 範圍 | 頻率 | 保留 | RPO | RTO | 失敗代價 |
|---|---|---|---|---|---|---|---|
| L1 | Lightsail AutoSnapshot | **整個 instance**(docker / `.env` / certs / data / OS) | 每日 UTC 22:00 | 7 份 | 24h | 30–60 min | 整機 down,還原慢但完整 |
| L2 | 本機 `devops.sh cmd_backup` + `backup_verify.sh` | `~/knowledge_graph_api/`(rsync 增量 + tar 到本機) | 手動(發版前 / 事故前) | 全部歷史(本機磁碟) | 視操作時機 | 5–10 min | 本機磁碟掛 |
| L3 | AWS S3(本 SOP) | `data/`(tar+gz streaming) | 每日 UTC 03:00 (cron) | Versioning + **MFA Delete**,**無 lifecycle**(AWS 限制兩者互斥)→ 永久累積,需手動清(見 `backup_restore.md §7`) | 24h | ~15 min | S3 region 級故障 |

## 為什麼三層

- L1 救「整個 instance 被誤刪」、「Docker 配置壞掉」。粒度粗,但唯一能還原 `.env` / `certs`。
- L2 救「我在發版前怕剛改的 schema 壞了」、「想對比 5/15 vs 5/20 的某張表」— 任意時間點手動拉。沒自動,純人工保險。
- L3 救「server 上一切被 `rm -rf`,SSH key 也鎖在被刪的目錄裡」(2026-05-30 真實案例)。IAM 邊界硬隔絕,server 角色只能 PutObject、刪不掉歷史。

## 不在範圍(共識)

| 缺項 | 原因 | follow-up |
|---|---|---|
| 跨 region replication | RPO 24h 同 region 已夠;成本 |  |
| 跨雲(R2 / GCS / B2) | 過度防護 |  |
| PITR / SQLite WAL streaming | RPO 24h 達標 |  |
| Backup 完整性 alarm | 之後再加,CloudWatch alarm + SNS |  |
| 自動清舊 backup | **AWS 限制**:lifecycle 與 MFA Delete 不可共存,選了 MFA Delete | 約 1-2 年後手動清一次(`backup_restore.md §7`);成本閾值與動作判準走 `docs/reference/cost_baseline.md` **(SoT)** |
| `.env` / `certs/` 異地 backup | 本機 Time Machine 涵蓋,且都可重生 | 月度 reminder:檢查本機 backup 含 `~/.ssh/`、`~/kg/backend/{.env,certs/}` |

## 監控

每週看一次:

```bash
# L1
aws lightsail get-auto-snapshots --resource-name booksbrowser-kg-api-2gb | jq '.autoSnapshots | length'

# L3
aws s3 ls s3://kg-backups-prod-967512079054/data/ | wc -l
ssh ubuntu@13.193.212.134 'sudo tail -5 /var/log/kg_backup.log'
```

任一連 2 天沒新增 = ping。

## 相關文件

- `docs/sop/backup_restore.md` — restore step-by-step(事故當下讀這份)
- `docs/sop/debug.md` — 排障(含 502 / Caddy / Docker)
- `docs/sop/deploy.md` — 部署(含 instance 重建流程)
- `docs/runbook/system.md` — change flow
- `ops/kg_backup.sh` / `ops/cron/kg-backup.cron` — L3 實作
