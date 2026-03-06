# Super-Repo + Submodule Workflow

## Topology
- Workspace root is the control-plane repo.
- `booksbrowser_ios` and `knowledge_graph_api` are submodules.
- Root commit records exact child commit SHAs (release pairing source of truth).

## Day-to-Day Flow

### A) iOS-only change
1. `cd booksbrowser_ios`
2. Implement + test + commit
3. `cd ..`
4. `git add booksbrowser_ios`
5. Commit root pointer update (and optional release note/docs)

### B) API-only change
1. `cd knowledge_graph_api`
2. Implement + test + commit
3. `cd ..`
4. `git add knowledge_graph_api`
5. Commit root pointer update

### C) Cross-project release
1. Commit iOS repo
2. Commit API repo
3. At root, stage both submodule pointers
4. Commit one root "release alignment" commit

## Read/Write Rules For Agents
- Always decide scope first: `ios` / `api` / `workspace`.
- Never commit iOS code from root repo.
- Never commit API code from root repo.
- Root repo should only track coordination artifacts + submodule pointers.

## Useful Commands
```bash
# root status (shows submodule pointer drift)
git status

# current paired SHAs
git submodule status

# inspect child states
git -C booksbrowser_ios status --short
git -C knowledge_graph_api status --short
```

## No-Remote Mode (Current Setup)
This setup can run fully local without remotes.
- Child repos remain normal git repos.
- Root repo still provides pairing/audit via local commits.
- Remote can be added later with:

```bash
git remote add origin <workspace-remote>
git push -u origin main
```

## Recommended Commit Message Convention (Root)
- `chore(workspace): align ios/api submodule pointers`
- `docs(workspace): update deploy/runbook`
- `release(workspace): pair ios <sha> with api <sha>`
