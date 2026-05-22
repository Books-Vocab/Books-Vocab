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
