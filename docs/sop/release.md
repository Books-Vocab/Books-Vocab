<!-- doc-meta
tier: sop
authority: derived
update_trigger: release-change
scope:
  - .github/workflows/
  - ops/release.sh
  - ops/release_report.py
  - ops/devops_kg_safe.sh
  - ops/kg_reconcile.sh
  - backend/
  - ios/
verified_against: 51ce9228ce64c1897850b8fcab672364b17f8731
-->
# Release SOP

## Mental model

[`docs/reference/delivery_model.md`](../reference/delivery_model.md) 定義 CM 對 codebase、merge 與 release／deploy 邊界的責任。GitHub `main` is the merged product truth. A PR merge records code review and required checks; it is not by itself permission to publish or deploy. A release is an explicit, traceable action with a version, target surface, approval, health verification and rollback path.

| Concern | Source of truth | Entry |
|---|---|---|
| Code and review | GitHub PR merged to `main` | GitHub |
| Version and release notes | repository release metadata | `ops/release.sh status/changelog` |
| Backend production state | production ref／container health | `ops/release.sh` + `ops/devops_kg_safe.sh` |
| iOS build/TestFlight | App Store Connect and build artifacts | `docs/sop/ios.md`、`ops/ios_release.sh` |
| Cross-surface release diff | Git anchors + ASC + live probe | `ops/release_report.py` |
| Rollback | previous known-good version／image／ref | deploy SOP and safety wrapper |

## Required sequence

1. CM confirms the PR is merged to the intended `main` and the merged SHA is known.
2. Run release status and inspect changed surfaces, migrations, configuration and compatibility risks.
3. Select backend, iOS, or both. Do not publish a surface that was not explicitly selected.
4. Run the release entrypoint in dry-run mode first. Confirm target, version, approval and rollback candidate.
5. Execute only the approved release command. Production writes must pass the safety wrapper and health gate.
6. Verify the deployed/build state independently and record the exact version and evidence.
7. If health verification fails, stop traffic or revert according to `docs/sop/deploy.md`; do not improvise a second path.

## Backend

Use `ops/release.sh` as the release entry and `ops/devops_kg_safe.sh` for remote or production operations. `ops/kg_reconcile.sh` is the host-side convergence service when enabled; its health gate and rollback behavior are part of the deployment contract. Database migrations, secrets, domain routing, container ports and host ownership remain governed by `docs/sop/deploy.md` and `docs/reference/host_topology.md`.

## iOS

Use `docs/sop/ios.md` for signing, build, TestFlight and App Store Connect operations. Keep build verification, metadata changes and submission as separate decisions; an uploaded build is not an approved store release.

## Cross-surface provenance report

Before answering a version-gap question, run the read-only report so the answer is bound to
the same evidence window:

```bash
./ops/release_report.py snapshot
./ops/release_report.py snapshot --json
```

The report keeps Git, App Store Connect and backend live state separate. `ios/<version>+<build>`
is the source binding for a TestFlight binary; `ios/<version>` is the shipped App Store source
binding created only after the ASC state is verified. For backend, compare `origin/prod` to
`origin/main`, then separately compare live `/api/system/info` to `origin/prod`. Missing source
bindings are `blocked`, never a guessed match.

每次 `snapshot` 也會以 `git ls-remote` 重新確認 `origin/main` 與 `origin/prod`；只
相信本地 remote-tracking ref 會把「本地看起來最新」誤報成目前遠端狀態。若 remote
ref 過期、無法取得或 live backend version 無法解析到 commit/tree，報告會
`blocked`，不會繼續計算看似精確的差距。

App Store／TestFlight 的 tuple 比對必須同時有 ASC 的 version、build number 與 build
resource identity。缺少 App Store `READY_FOR_SALE` version 或其 build、或缺少
TestFlight build binding 時，報告同樣是 `blocked`；不可用「最新 TestFlight build」
代替使用者實際取得的 App Store 版本。

### Provenance contract

「版本」不是一個字串，而是可交叉驗證的 release identity：

```text
iOS = bundle id + marketing version + build number + ASC build id
      + source commit/tree + immutable ios/<version>+<build> tag
      + TestFlight/App Store channel state
backend = source commit/tree + origin/prod + live /api/system/info version
```

Authority 必須保持分離：

| 問題 | Authority | 不可替代的理由 |
|---|---|---|
| iOS build 的 source snapshot | Git `ios/<version>+<build>` tag | ASC 不保留 source commit；缺 tag 就是 `unbound` |
| TestFlight binary/channel | App Store Connect build API | 不可由 local archive、時間戳或版號猜測 |
| App Store user-facing release | App Store Connect `READY_FOR_SALE` version | TestFlight 最新 build 不等於已上架 |
| backend 期望 state | Git `origin/prod` | `main` 不是 production |
| backend 實際 serving state | live `GET /api/system/info` | `origin/prod` 不是 runtime proof |

報告 schema 是 `kg.release.report.v1`；`aligned` 代表證據完整且沒有差異，`drift`
代表證據完整但有可量測差異，`blocked` 代表 anchor 缺失或 external probe 不可用。
exit code `0` 可報告 aligned/drift，exit code `2` 只能報告 partial/blocked。

常見問題的固定讀法：

- 「生產 backend 和 main」看 `backend.productionToMain`（`origin/prod → origin/main`），再看 `backend.production.liveAlignment`。
- 「TestFlight 和 App Store」先比 `ios.testflight`／`ios.appStore` 的 ASC tuple，再比 `ios.appStoreToTestFlight` source diff。
- 「main 和 PR」用 PR 的 exact head 做 `diff --from origin/main --to <pr-head>`；PR open/draft/checks/CR/DS 仍以 GitHub PR 為準，local diff 不代表已 merge。

報告只讀 Git、ASC GET 與 live GET，不建立第二套狀態庫；`--ipa` 只提供本地 IPA
SHA-256，不能宣稱該檔案就是 ASC binary。

## Hard stops

- No production action without explicit release intent and approval.
- No force-push, destructive cleanup or guessed rollback target.
- No claim of release success without current health／store evidence.
- If a required external approval can only be performed by the account owner, report it immediately and continue only with safe parallel work.
