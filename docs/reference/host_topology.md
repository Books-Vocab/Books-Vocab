<!-- doc-meta
tier: reference
authority: SoT
update_trigger: code-change
scope:
  - ops/
  - docs/policy/
verified_against: 41bf8dd
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

## Data Persistence
- KG API: `~/knowledge_graph_api/data`

## Agent Operation Entry
- Entry: `CLAUDE.md`
