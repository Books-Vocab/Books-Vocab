<!-- doc-meta
tier: reference
authority: SoT
update_trigger: code-change
scope:
  - ops/
  - docs/policy/
verified_against: 6067f0c
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
| Antigravity Proxy | `lab/antigravity-proxy` | `~/antigravity-proxy` | `wordnexus.lol/ag/*` | `3000` | `antigravity-proxy-proxy-1` |

## Routing
```caddy
wordnexus.lol {
    handle /claude/* {
        uri strip_prefix /claude
        reverse_proxy localhost:8090
    }
    handle /ag/* {
        @authed header Authorization "Bearer <CADDY_AG_TOKEN>"
        handle @authed {
            uri strip_prefix /ag
            reverse_proxy localhost:3000
        }
        respond 401
    }
    reverse_proxy localhost:8000
}
```

`/ag/*` handle 必須**插在 catch-all `reverse_proxy localhost:8000` 之前**，否則會被 KG API 吃掉。Bearer token 比對由 Caddy 層擋（值存 host `/etc/caddy/Caddyfile`，不在 git）。

## Security Posture
- Public ports: `22/80/443` only.
- Caddy terminates TLS and reverse proxies to local containers.

## Data Persistence
- KG API: `~/knowledge_graph_api/data`
- Antigravity Proxy: `~/antigravity-proxy/data`（OAuth refresh tokens；不在 git）

## Agent Operation Entry
- Entry: `CLAUDE.md`
