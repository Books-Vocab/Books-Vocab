# PR Timeline

Private, read-only merged-PR timeline for `Books-Vocab/Books-Vocab`.

## Surface

- `GET /` — one horizontal timeline with PR markers and a zoom slider.
- `GET /api/prs` — normalized GitHub PR data plus sync/cache status.
- `GET /healthz` — `200` after a successful sync or when usable cached data exists; otherwise `503`.
- Felix bind: `100.118.39.104:8008` only. Do not bind `0.0.0.0` or put this service behind Cloudflare.

The service uses Felix's existing host-side `gh` authentication. It never writes a GitHub token to the plist, repository, or cache. The cache is `/Users/chenliangyu/.local/state/kg-pr-timeline/prs.json`.

## Local check

```bash
uv run --no-project --python 3.13 python ops/pr_timeline/server.py --host 127.0.0.1 --port 8008
```

## Felix release layout

Each deployment is an immutable release directory:

```text
/Users/chenliangyu/services/kg-pr-timeline/releases/<commit-sha>/
/Users/chenliangyu/services/kg-pr-timeline/current -> releases/<commit-sha>/
```

The user-level LaunchAgent is `/Users/chenliangyu/Library/LaunchAgents/com.kg.pr-timeline.plist` and points only at `current`. The safe launch/stop entrypoints are:

```bash
launchctl bootstrap gui/$(id -u) /Users/chenliangyu/Library/LaunchAgents/com.kg.pr-timeline.plist
launchctl bootout gui/$(id -u)/com.kg.pr-timeline
launchctl print gui/$(id -u)/com.kg.pr-timeline
```

Deploy by fetching the pushed commit into Felix's existing clone, archiving only that exact commit's declared service files into a new release directory, switching `current`, installing the plist, then bootstrapping the LaunchAgent. Do not checkout or reset Felix's shared `main` worktree.

## Rollback

Capture the prior `current` symlink target and plist checksum before every deploy. To restore a previous release, stop first, point `current` back to the captured release, restore the captured plist, then bootstrap:

```bash
launchctl bootout gui/$(id -u)/com.kg.pr-timeline || true
ln -sfn /Users/chenliangyu/services/kg-pr-timeline/releases/<previous-sha> /Users/chenliangyu/services/kg-pr-timeline/current
cp /Users/chenliangyu/services/kg-pr-timeline/current/ops/launchd/com.kg.pr-timeline.plist /Users/chenliangyu/Library/LaunchAgents/com.kg.pr-timeline.plist
launchctl bootstrap gui/$(id -u) /Users/chenliangyu/Library/LaunchAgents/com.kg.pr-timeline.plist
```

If the pre-deploy state has no service, the exact restore is `launchctl bootout ... || true` followed by moving the newly installed plist to a `.rollback-<sha>` name. No release or cache data is deleted.
