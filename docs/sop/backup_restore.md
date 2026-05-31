<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - ops/kg_backup.sh
  - ops/cron/kg-backup.cron
verified_against: 61b0d14f
-->
# Backup / Restore SOP

> 「沒做過 restore 演練 = 薛丁格的 backup」。本文是 KG 生產 SQLite 資料(`/home/ubuntu/knowledge_graph_api/data/`)從 AWS S3 異地 backup **完整還原**的 step-by-step。事故當下下一個 agent 直接讀這份即能恢復服務,**不需問人**。

---

## 0. 受 backup 涵蓋的內容

`/home/ubuntu/knowledge_graph_api/data/`:

| 子目錄 | 內容 |
|---|---|
| `users/<user_id>/cards.db` | 詞庫 / KG / 學習紀錄 |
| `users/<user_id>/daily_review_stats.db` | TodayReview 統計 |
| `users/users.json` | user index |
| `podcasts/<series_id>/...` | podcast 音頻 + metadata(Track B 遷移完成後改由 S3 直接保留,本 backup 仍含過渡期 disk-mode 資產) |
| `judge_log.db` | 評審 log |

**不含**:`.env`、`certs/`、`compose.yml`、docker images(這些由 git + scp 流程恢復)。

---

## 1. Backup 配置(現況)

| 項目 | 值 |
|---|---|
| Bucket | `kg-backups-prod-967512079054` |
| Region | `ap-northeast-1` |
| Versioning | Enabled + **MFA Delete**(由 root user 設) |
| Public access | Block all |
| Encryption | SSE-S3 (AES256) |
| Lifecycle | current versions expire 30 天;noncurrent 35 天後 permanently delete |
| Key 格式 | `data/YYYY-MM-DD.tar.gz`(UTC 日期) |
| Cron | `/etc/cron.d/kg-backup` → 每天 UTC 03:00(台北 11:00) |
| Script | `/usr/local/bin/kg_backup.sh`(root:root, 755) |
| Log | `/var/log/kg_backup.log`(每執行一行) |
| IAM | `kg-backup-agent` 僅 `s3:PutObject*`,**無 Delete / 無 List**(限制 blast radius) |
| 本機操作身份 | `MaxChen228`(admin),用 `~/.aws/credentials` 預設 profile |

防線層級:

1. **Lightsail AutoSnapshot** — 每日 UTC 22:00,保留 7 份。整個 instance 還原(含 docker、`.env`、`certs/`)。RTO 大、彈性低,但最 self-contained。
2. **本機 tar backup** — `devops.sh cmd_backup`(`backup_verify.sh` 拉到 `~/kg/backups/`)。事故時若 server 已壞、S3 也壞,此為最後一道。
3. **AWS S3 異地 backup** — 本 SOP。粒度小、最近 30 天可逐日選版本。

---

## 2. Restore — 標準流程(RTO ~15 分鐘)

> 假設場景:`data/` 目錄被誤刪 / DB 損壞 / 需回到指定日期。Lightsail instance 本身可達。

### 2.1 列出可用 backup

```bash
# 列當前 versions
aws s3 ls s3://kg-backups-prod-967512079054/data/ --region ap-northeast-1

# 含 noncurrent versions(若某日 backup 被新版本覆蓋,可救回)
aws s3api list-object-versions \
  --bucket kg-backups-prod-967512079054 \
  --prefix data/ \
  --region ap-northeast-1 \
  --query 'Versions[].{Key:Key,VersionId:VersionId,LastModified:LastModified,Size:Size}' \
  --output table
```

### 2.2 確認目標 backup 的 sha256(從 server log)

```bash
ssh ubuntu@13.193.212.134 'sudo grep "<YYYY-MM-DD>" /var/log/kg_backup.log'
# 範例:
# 2026-05-31T16:14:42Z exit=0 bytes=353618986 sha256=61b9f656... key=data/2026-05-31.tar.gz
```

記下 sha256 與 size,等下校驗用。**沒 log 對照就不要 restore**(來源不可信)。

### 2.3 拉 backup 到 server(在 server 上跑,不要先拉到本機再 scp)

```bash
ssh ubuntu@13.193.212.134
cd /tmp
DATE=2026-05-31  # 改成你要還原的日期
aws s3 cp "s3://kg-backups-prod-967512079054/data/${DATE}.tar.gz" "/tmp/${DATE}.tar.gz" --region ap-northeast-1
```

> Server 上 `kg-backup-agent` IAM **僅有 PutObject**,如果遇 `AccessDenied`,改用本機 admin profile 拉再 scp:
> ```bash
> # 本機
> aws s3 cp "s3://kg-backups-prod-967512079054/data/${DATE}.tar.gz" /tmp/
> scp -i ~/.ssh/lightsail_kg_prod "/tmp/${DATE}.tar.gz" ubuntu@13.193.212.134:/tmp/
> ```

### 2.4 校驗 sha256

```bash
# 在 server 上
EXPECTED=61b9f656...  # 從 2.2 取得
ACTUAL=$(sha256sum /tmp/${DATE}.tar.gz | awk '{print $1}')
[[ "$EXPECTED" == "$ACTUAL" ]] && echo "✓ MATCH" || { echo "✗ MISMATCH"; exit 1; }
```

校驗失敗 → 改拉 noncurrent version(`--version-id <id>` 加在 `aws s3api get-object` 上)或退到 Lightsail Snapshot。

### 2.5 停容器、備份「壞掉的」現場、解壓覆蓋

```bash
cd /home/ubuntu/knowledge_graph_api

# 停容器,避免 SQLite WAL race
docker compose stop

# 把當前 data/ rename 成 data.broken.<ts>(別 rm,留鑑識用)
TS=$(date +%Y%m%d-%H%M%S)
sudo mv data "data.broken.${TS}" 2>/dev/null || true

# 解壓 — tarball 內第一層就是 data/,直接在 ~/knowledge_graph_api/ 解
tar xzf "/tmp/${DATE}.tar.gz"
ls -la data/users/ | head
```

### 2.6 修正 owner(容器 uid)

容器內 uid 是 `1000:1000`(host 上 `ubuntu` user 同 uid)。tar 預設保留原 owner,通常就是 ubuntu — 但若 backup 是 root 跑的 cron,owner 可能變 root,要修正:

```bash
sudo chown -R ubuntu:ubuntu data/
```

### 2.7 啟動 + 健康檢查

```bash
docker compose up -d
sleep 10
curl -s -o /dev/null -w 'docs=%{http_code}\n' http://127.0.0.1:8000/docs
curl -s https://wordnexus.lol/docs | head -5
docker compose logs --tail=30 kg-api
```

預期:`docs=200`、SwaggerUI 可載入、container log 無 startup error、`/api/system/info` 回 200。

### 2.8 抽樣驗證資料(SQLite integrity_check)

```bash
SAMPLE=$(ls -d data/users/*/ | head -1)
for db in "$SAMPLE"/*.db; do
  echo "--- $db ---"
  docker compose exec -T kg-api sqlite3 "/app/${db#./}" "PRAGMA integrity_check;"
done
```

預期每個 db 回 `ok`。

### 2.9 紀錄

事故時間、選用 backup 日期、sha256、影響期間、丟失資料窗口寫進 `docs/runbook/incidents/<date>.md`(若不存在就建,參考 `docs/runbook/system.md`)。

---

## 3. Restore — 災難情境(Lightsail instance 也掛)

優先順序:

1. **Lightsail Snapshot 還原 instance**(AWS Console → Lightsail → Snapshots → Create instance from snapshot)→ 上面已有 docker / `.env` / `certs/` → 進到 2 拉最新 S3 backup 覆蓋 data → 改 elastic IP 指到新 instance(或在 Caddyfile / iOS endpoint 切 DNS)。RTO 30–60 分鐘。
2. **完全空白 instance** → 重跑 `devops.sh deploy`(會 build image, scp `.env`, certs, compose, `VERSION`)→ 拉 S3 backup → 同 2.5–2.7。RTO 1–2 小時(主要卡 Docker build)。

> 已知陷阱:`compose.yml` 中 `./VERSION:/app/VERSION:ro` 是 bind mount file,如果 `VERSION` 不存在會被 Docker 當成目錄掛,容器秒退 exit 127。`deploy` 流程會寫 `VERSION`,手動還原時 `echo "$(git rev-parse --short HEAD)" > VERSION` 不要漏。

---

## 4. 故意搞壞:fire drill 演練

每月一次,選週末晨間:

```bash
# 1. 拉昨天的 backup 到 /tmp/scratch
DRILL=/tmp/restore-drill-$(date -u +%Y%m%d)
mkdir -p "$DRILL" && cd "$DRILL"
DATE=$(date -u -d 'yesterday' +%Y-%m-%d 2>/dev/null || date -u -v-1d +%Y-%m-%d)
aws s3 cp "s3://kg-backups-prod-967512079054/data/${DATE}.tar.gz" .
tar xzf "${DATE}.tar.gz"

# 2. sha256 比對(查 server log)
ssh ubuntu@13.193.212.134 "sudo grep ${DATE} /var/log/kg_backup.log"
sha256sum "${DATE}.tar.gz"

# 3. SQLite integrity check
for db in $(find data/users -name '*.db' -not -name '*-wal' -not -name '*-shm'); do
  echo "$db: $(sqlite3 "$db" 'PRAGMA integrity_check;' | head -1)"
done

# 4. 清掉
cd /tmp && rm -rf "$DRILL"
```

預期:所有 db 都 `ok`,sha256 與 server log 完全相符。**任何一個 db 不是 `ok` 就視為當天 backup 損壞**,立刻調查 cron 是否有時段碰到 SQLite WAL flush。

---

## 5. 故障排除

| 症狀 | 原因 | 處置 |
|---|---|---|
| `kg_backup.sh` exit=2 | `data/` 目錄缺 | container 還沒起 / path 改了。檢查 `KG_DATA_DIR` env |
| `aws` 寫入 `AccessDenied` | IAM `kg-backup-agent` 寫了 `s3:PutObject` 外的動作 | 不該發生。檢查 inline policy `kg-backup-put-only` |
| backup 連續 N 天大小驟減 | 用戶資料異常 / 路徑被偷改 | 不可信。回到上一個正常日期的 backup |
| sha256 不符 | 傳輸中斷或 S3 物件被改 | 改用 noncurrent version,並上 CloudTrail 查改動者 |
| `MFADelete=Enabled` 後想改 lifecycle | MFA 也鎖 PutBucketVersioning | root user + MFA code 重簽 versioning config(暫關 MFADelete → 改 → 再開) |

---

## 6. 已知不在 backup 範圍(顯式宣告)

| 不含 | 怎麼救 |
|---|---|
| `.env` | git 不在;`~/kg/backend/.env` 為本機真實檔(`.gitignore`)。事故時從本機 scp 還原。Pre-flight 應該每月把 `.env` 加密後丟個保險櫃。 |
| `certs/AuthKey_*.p8` | Apple Developer Portal 重下載或 `~/Downloads/` 找。**這也應有本機定期備份**。 |
| Docker images | `docker compose build` 重 build。耗時但確定可重現。 |
| Lightsail SSH key | `~/.ssh/lightsail_kg_prod`。**本機備份必含 `~/.ssh/`**(每日 Time Machine 已含)。掉了 → Lightsail Console 改用 Browser-based SSH 或 EC2 Instance Connect 重塞 pubkey。 |

---

## 7. 反向操作(刻意刪 backup)

正常運維**不需要**手動刪 S3 backup,lifecycle 會自動清。但若要刪:

```bash
# 仍要 MFA。bucket 沒開 MFADelete 時跳過 --mfa 旗標
aws s3api delete-object \
  --bucket kg-backups-prod-967512079054 \
  --key "data/<date>.tar.gz" \
  --version-id "<id>" \
  --mfa "arn:aws:iam::967512079054:mfa/<device> <code>"
```

**`kg-backup-agent` 完全沒有 Delete 權限**,要刪只能用本機 admin profile。這是設計上的硬阻擋,不要繞過。
