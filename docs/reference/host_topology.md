<!-- doc-meta
tier: reference
authority: SoT
update_trigger: code-change
scope:
  - ops/
  - docs/policy/
verified_against: 800386c5
-->
# Host Background (Single Source of Truth)

## Host
- Provider: AWS Lightsail
- Instance: `booksbrowser-kg-api-2gb` (small_3_0, 2GB RAM, 60GB disk)
- Region: `ap-northeast-1`
- OS: Ubuntu 24.04
- Edge Proxy: Caddy (80/443)

## Service Map
| Project | Canonical Local Path | Remote Path | Domain | Internal Port | Container |
|---|---|---|---|---|---|
| KG API | `backend` | `~/knowledge_graph_api` | `wordnexus.lol` | `8000` | `knowledge-graph-api` |
| Claude Gateway | `lab/claude-code-gateway` | `~/claude-code-gateway` | `wordnexus.lol/claude/*` | `8090` | `claude-code-gateway-api-1` |

> Antigravity Proxy（`lab/antigravity-proxy/`）**不在 VPS 上**：2026-05-23 撤出公網改純本機執行（封號風險考量），詳見 `docs/sop/antigravity-proxy.md`。
>
> Codex Gateway（`lab/codex-gateway/`，ChatGPT 訂閱 → OpenAI-compatible API）**不在 VPS 上**：從一開始就純本機 `127.0.0.1:2455` 部署（OpenAI 反濫用偵測雖無 ban wave 實證，但具備所有觸發條件，預防性 air-gap）。詳見 `docs/sop/codex-gateway.md`。

## Routing

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

## Security Posture
- Public ports: `22/80/443` only.
- Caddy terminates TLS and reverse proxies to local containers.
- **Rate-limit / XFF 契約**:單層 bare Caddy 直連 AWS 公網(無 CDN/ALB)會把真實 client IP **append 到 X-Forwarded-For 尾段**,故匿名 rate-limit key 取倒數第 1 段即真實 IP。此契約由 `RATE_LIMIT_TRUSTED_HOPS`(default `1`)編碼;**若未來前置 N 層可信代理(CDN/ALB)務必同步設 `RATE_LIMIT_TRUSTED_HOPS=N+1`**,否則限流會 key 到可被偽造的最內層代理 IP。

## Data Persistence
- KG API: `~/knowledge_graph_api/data`

## Agent Operation Entry
- Entry: `CLAUDE.md`
