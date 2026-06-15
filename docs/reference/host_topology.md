<!-- doc-meta
tier: reference
authority: SoT
update_trigger: code-change
scope:
  - ops/
  - docs/policy/
verified_against: d67bed12
-->
# Host Background (Single Source of Truth)

> **過渡狀態（2026-06-15 起）**：正式站 `wordnexus.lol` 已從 AWS Lightsail 遷到家用常駐機 `standby`，經 **Cloudflare Tunnel** 對外。Lightsail 容器**已 STOP**（未 terminate），保留 1-2 週當 rollback。hostname 全程不變 → iOS app / Apple 推播 / Google OAuth 零改動。
> 服務層部署正本（含 tunnel ID / CF zone / reboot 復活鏈）在 butler `~/butler/docs/kg-backend-deployment.md`；機器層建置在 `~/butler/docs/standby-host-setup.md`。本檔是 kg repo 內的 host topology SoT。

## Host（primary，2026-06-15 起）
- 角色：正式站常駐機
- 機器：`chenliangyusAir`（M3 Air），user `chenliangyu`
- 位址：Tailscale `100.118.39.104`（主力機 `ssh chenliangyu@100.118.39.104` 免密碼）
- OS：macOS（Asia/Taipei, UTC+8）
- 容器引擎：OrbStack docker（`app.start_at_login=true`）
- Edge：**Cloudflare Tunnel**（CF 邊緣終結 TLS，憑證 CF 託管）；**無 Caddy、不開任何 inbound 埠**（cloudflared 主動 outbound）

## Host（rollback，STOPPED）
- Provider: AWS Lightsail
- Instance: `booksbrowser-kg-api-2gb` (small_3_0, 2GB RAM, 60GB disk)
- Region: `ap-northeast-1`
- OS: Ubuntu 24.04
- IP: `13.193.212.134`
- Edge Proxy: Caddy (80/443)
- 狀態：容器 **STOP**（資料停留在遷移當下快照），Caddy 仍在。回滾程序見下方 §Rollback。

## Service Map
| Project | Canonical Local Path | Primary（standby）| Rollback（Lightsail）| Domain | Internal Port | Container |
|---|---|---|---|---|---|---|
| KG API | `backend` | `~/project/kg/backend`（git 同步） | `~/knowledge_graph_api` | `wordnexus.lol` | `8000` | `knowledge-graph-api` |

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

## Rollback（standby → Lightsail，緊急）

Lightsail 容器只是 STOP，資料還在遷移當下快照。回滾步驟：
1. 啟動 Lightsail 容器：`ssh -i ~/.secrets/lightsail_kg_prod ubuntu@13.193.212.134 'cd ~/knowledge_graph_api && docker compose up -d'`
2. CF apex 從 tunnel proxied CNAME 改回 **A → `13.193.212.134`**（grey/DNS-only），用 `~/.secrets/cloudflare_token`。
- ⚠ **資料分岔風險**：standby 上線後產生的新資料**不在** Lightsail 快照。回滾 = 丟掉切換後的寫入。僅限「standby 嚴重故障且短期內無法修」的災難情境。
- 完整回滾與 DNS 委派傳播坑見 butler `~/butler/docs/kg-backend-deployment.md §6 / §8`。

## Security Posture（primary）
- **無 inbound 開埠**：cloudflared 主動 outbound 連 CF 邊緣，家用機不需公網 IP、不需開 80/443。
- **TLS 由 CF 邊緣終結**（憑證 CF 託管），standby 容器內無憑證管理。
- **Rate-limit / XFF 契約**：CF 邊緣後置疊一層 XFF。但 iOS app 全程帶 JWT，rate-limit key 按 token 後 16 碼計（CF 無影響）；CF 標準 XFF = 真 client 單段附在尾端 → `RATE_LIMIT_TRUSTED_HOPS`（default `1`）取倒數第 1 段仍正確。**若未來把 tunnel 換成多層可信代理務必同步調整 `RATE_LIMIT_TRUSTED_HOPS`**，否則匿名限流會 key 到可被偽造的代理 IP。（僅匿名+非豁免端點理論需驗，見 butler §7 G2。）

## Reboot 自動復活鏈（standby SPOF，無 UPS）
1. 斷電復電 → macOS `autoLoginUser=chenliangyu` 自動登入（FileVault 已關）
2. OrbStack `app.start_at_login=true` → 引擎啟動
3. 容器 `restart: always` → 引擎起來後自動拉起
4. cloudflared system LaunchDaemon（`RunAtLoad`）→ 開機即起接上 CF 邊緣

→ 全自動恢復對外服務（config 已逐項驗，真 reboot 演練待補）。

## Data Persistence
- KG API（primary）：`~/project/kg/backend/data`（~403M；12 用戶 + root DB）
- KG API（rollback）：`~/knowledge_graph_api/data`

## Agent Operation Entry
- Entry: `CLAUDE.md`
