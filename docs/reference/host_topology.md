<!-- doc-meta
tier: reference
authority: SoT
update_trigger: code-change
scope:
  - ops/
  - docs/policy/
verified_against: 10586683d
-->
# Host Background (Single Source of Truth)

> **狀態（2026-06-15 遷移，2026-06-16 Lightsail 下架）**：正式站 `wordnexus.lol` 已從 AWS Lightsail 遷到家用常駐機 `standby`，經 **Cloudflare Tunnel** 對外。**Lightsail instance `booksbrowser-kg-api-2gb` 已於 2026-06-16 完全 terminate**（含 7 份 auto-snapshot + addon 排程，全區域零計費資源驗證）。原「啟動已停容器」的快速回滾路徑不再存在；回滾 = 從零冷重建（見 §Rollback / 重新上架）。hostname 全程不變 → iOS app / Apple 推播 / Google OAuth 零改動。
> 服務層部署正本（含 tunnel ID / CF zone / reboot 復活鏈）在 butler `~/butler/docs/kg-backend-deployment.md`；機器層建置在 `~/butler/docs/standby-host-setup.md`。本檔是 kg repo 內的 host topology SoT。

## Host（primary，2026-06-15 起）
- 角色：正式站常駐機
- 機器：`chenliangyusAir`（M3 Air），user `chenliangyu`
- 位址：Tailscale `100.118.39.104`（主力機 `ssh chenliangyu@100.118.39.104` 免密碼）
- OS：macOS（Asia/Taipei, UTC+8）
- 容器引擎：OrbStack docker（`app.start_at_login=true`）
- Edge：**Cloudflare Tunnel**（CF 邊緣終結 TLS，憑證 CF 託管）；**無 Caddy、不開任何 inbound 埠**（cloudflared 主動 outbound）

## Host（rollback，TERMINATED 2026-06-16）
- Provider: AWS Lightsail（已下架）
- 原 Instance 規格（重建用）：`booksbrowser-kg-api-2gb`，blueprint `ubuntu_24_04`，bundle `small_3_0`（2GB RAM / 40GB SSD），AZ `ap-northeast-1a`
- 原 IP `13.193.212.134`（動態，已隨 instance 釋放，**勿再引用**）
- Edge Proxy: Caddy (80/443)
- 狀態：**已完全 terminate**（instance + 系統碟 + 7 份 auto-snapshot + auto-snapshot addon 排程全刪，全 16 區域零計費資源已驗）。原「資料停留在遷移當下快照」那份 rollback 資料已隨 terminate 消失——standby 是唯一權威。重新上架程序見下方 §Rollback / 重新上架。

## Service Map
| Project | Canonical Local Path | Primary（standby）| Rollback（Lightsail）| Domain | Internal Port | Container |
|---|---|---|---|---|---|---|
| KG API | `backend` | `~/kg-prod/backend`（生產 checkout，追 origin/prod，reconciler 從此 build） | `~/knowledge_graph_api` | `wordnexus.lol` | `8000` | `knowledge-graph-api` |

> **兩個 felix checkout（三平面拓樸）**：`~/kg-prod` 是**生產 checkout**（reconciler 盯 origin/prod、compose 從 `~/kg-prod/backend` build，見 §Routing「自動部署常駐」）；`~/project/kg` 是 **dev / resume-only**（人手 `git pull` 追 main，reconciler 絕不碰——同 project name `backend` 若在此跑 compose 會劫持生產容器）。三平面 develop/backup/release 與切換 runbook 見 [`docs/sop/release.md`](../sop/release.md)。

## Routing（primary：Cloudflare Tunnel）

```
用戶 / iOS app
  → Cloudflare DNS（apex，proxied CNAME-flatten → tunnel，orange cloud，SSL 模式 full）
  → CF 邊緣（anycast，終結 TLS，憑證 CF 託管）
  → cloudflared 隧道（standby outbound 主動連出，無 inbound 開埠）
  → standby localhost:8000
  → OrbStack docker 容器 knowledge-graph-api（FastAPI）
```

- **tunnel**：名 `kg-standby`，id `03ad6631-8cc5-48b5-b938-a777377db160`，路由 CNAME 目標 `<id>.cfargotunnel.com`
- **CF zone**：`dd3884683faa95a0de686e8830d1d8ae`；NS `damien/gabriella.ns.cloudflare.com`；anycast IP `104.21.85.113` / `172.67.204.212`
- **ingress**（remotely-managed，存 CF 端，非本地 yaml）：`wordnexus.lol → http://localhost:8000`，fallback `http_status:404`
- **連接器常駐**：standby `/Library/LaunchDaemons/com.cloudflare.cloudflared.plist`（system daemon，`RunAtLoad` + `KeepAlive`，開機即起免登入）
- **自動部署常駐**：standby `~/Library/LaunchAgents/com.kg.reconcile.plist`（per-user LaunchAgent，`StartInterval=90` 週期 poller、`RunAtLoad`、**不 KeepAlive**）跑 `ops/kg_reconcile.sh --once`（生產 clone `~/kg-prod`，由 `KG_RECON_REPO` 指定），讓 **`origin/prod`** 一前進（三平面 release 平面，只有 `deploy` 推進；含 backend 變更）就自動收斂生產容器；`origin/main` 已降為 backup 鏡像，reconciler 不看 main。與 `devops.sh` 人工 deploy 共用 `/tmp/kg-deploy.lock`。機制/path-filter/rollback+poison 見 [`docs/sop/deploy.md`](../sop/deploy.md) §reconciler；三平面語意與首次 origin/main→origin/prod 切換 runbook 見 [`docs/sop/release.md`](../sop/release.md)。（由操作者手動 bootstrap 啟用，非預設掛載。）
- registrar = **Porkbun**（僅註冊；DNS 託管已移到 CF）
- 直打 CF 邊緣驗服務本身（排除 DNS 干擾）：`curl --resolve wordnexus.lol:443:104.21.85.113 https://wordnexus.lol/api/system/info`

## Routing（rollback：Lightsail + Caddy，僅回滾時生效）

> Caddyfile lives on VPS only (`/etc/caddy/Caddyfile`), not in repo — snippet below is reference only.

```caddy
wordnexus.lol {
    handle /claude/* {
        uri strip_prefix /claude
        reverse_proxy localhost:8090
    }
    reverse_proxy localhost:8000
}
```

## Rollback / 重新上架（Lightsail 冷重建）

> Lightsail 已 terminate，**無「啟動已停容器」的快速回滾**。標準正式站是 standby 家用機；Lightsail 僅作災難備援，平時不需要。下列為從零重建 Lightsail 正式站的完整步驟（架構/腳本已保留，可重現）。

**1. 建 instance（對齊原規格）**
```bash
aws lightsail create-instances \
  --instance-names booksbrowser-kg-api-2gb \
  --availability-zone ap-northeast-1a \
  --blueprint-id ubuntu_24_04 --bundle-id small_3_0 \
  --region ap-northeast-1
```

**2. 開放防火牆埠**（443 對外；80 給 ACME/redirect；22 建議鎖管理 IP 而非 `0.0.0.0/0`）
```bash
for p in 80 443; do aws lightsail open-instance-public-ports --instance-name booksbrowser-kg-api-2gb \
  --port-info fromPort=$p,toPort=$p,protocol=TCP --region ap-northeast-1; done
# 22 限自己 IP：--port-info fromPort=22,toPort=22,protocol=TCP,cidrs=<YOUR_IP>/32
```

**3. SSH 進入**：`aws lightsail download-default-key-pair --region ap-northeast-1` 取私鑰（chmod 600）→ `ssh -i <key> ubuntu@<新IP>`。

**4. Bootstrap**：`apt install -y docker.io docker-compose-plugin caddy` → `git clone <repo> ~/knowledge_graph_api`。

**5. 放 .env**（生產 secrets，從 standby `~/project/kg/backend/.env` 取，**勿入庫**）。

**6. Caddyfile** `/etc/caddy/Caddyfile`（見上方 §Routing rollback 區塊）→ `systemctl restart caddy`。

**7. 起服務**：`cd ~/knowledge_graph_api && docker compose up -d --build` → migrate → health。

**8. 切 DNS**：CF apex 從 tunnel proxied CNAME 改 **A → 新 IP**（grey/DNS-only），用 `~/.secrets/cloudflare_token`。

- ⚠ **資料分岔風險**：重建站是空的（舊 rollback 快照已隨 terminate 消失）。災難回滾須先把 standby 當下 data 搬上去（`devops_kg_safe.sh` 備份 → scp）。
- 完整 bootstrap / deploy / DNS 委派傳播坑見 butler `~/butler/docs/kg-backend-deployment.md`。

## Security Posture（primary）
- **無 inbound 開埠**：cloudflared 主動 outbound 連 CF 邊緣，家用機不需公網 IP、不需開 80/443。
- **容器 port 綁 loopback（2026-06-16 收斂）**：`docker-compose.yml` 將 8000 綁 `127.0.0.1:8000:8000`（非 `0.0.0.0`）。origin 只接受來自 cloudflared（localhost）的連線。**綁 `0.0.0.0` 會讓 8000 暴露在家用 LAN（`192.168.50.x`）與 Tailscale tailnet（`100.118.39.104`），任何同網段/同 tailnet 裝置可繞過 Cloudflare Tunnel 直打 origin（含 `/admin` 與全部 `/api/*`，後者仍受各自 JWT 守，但攻擊面無謂擴大）。** 維運查健康改走 `wordnexus.lol`（經 CF）或 ssh 進機器打 localhost；`devops_kg_safe.sh`（ssh + docker exec）不受影響。
- **TLS 由 CF 邊緣終結**（憑證 CF 託管），standby 容器內無憑證管理。
- **Rate-limit / XFF 契約**：CF 邊緣後置疊一層 XFF。但 iOS app 全程帶 JWT，rate-limit key 按 token 後 16 碼計（CF 無影響）；CF 標準 XFF = 真 client 單段附在尾端 → `RATE_LIMIT_TRUSTED_HOPS`（default `1`）取倒數第 1 段仍正確。**若未來把 tunnel 換成多層可信代理務必同步調整 `RATE_LIMIT_TRUSTED_HOPS`**，否則匿名限流會 key 到可被偽造的代理 IP。（僅匿名+非豁免端點理論需驗，見 butler §7 G2。）

## Reboot 自動復活鏈（standby SPOF，無 UPS）
1. 斷電復電 → macOS `autoLoginUser=chenliangyu` 自動登入（FileVault 已關）
2. OrbStack `app.start_at_login=true` → 引擎啟動
3. 容器 `restart: always` → 引擎起來後自動拉起
4. cloudflared system LaunchDaemon（`RunAtLoad`）→ 開機即起接上 CF 邊緣

→ 全自動恢復對外服務（config 已逐項驗，真 reboot 演練待補）。

## Data Persistence
- KG API（primary）：`~/kg-data`（felix；~403M；12 用戶 + root DB）—— 唯一權威。2026-06-16 移出 git worktree（原 `backend/data`），由 `KG_DATA_DIR` 指向、compose 掛為容器 `/app/data`（dev/deploy 隔離：git reset/clean 不再碰 live data）
- KG API（rollback）：~~`~/knowledge_graph_api/data`~~ 已隨 Lightsail terminate（2026-06-16）消失；冷重建站需從 standby 搬資料

## Agent Operation Entry
- Entry: `CLAUDE.md`
