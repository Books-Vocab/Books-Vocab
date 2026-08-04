<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - ops/
  - backend/
verified_against: 935fb9d2e
-->
# Release / 部署 / 版本管理 — 三平面心智模型

> 拓樸事實 SoT 見 [`docs/reference/host_topology.md`](../reference/host_topology.md)；後端手動部署細節見 [`docs/sop/deploy.md`](deploy.md)；iOS 出 build / TestFlight 見 [`docs/sop/ios.md`](ios.md) §發版。本文是**跨前後端的 release 流程正本**。

## 為什麼三平面

`git push origin main` 本來身兼兩職：**備份**（推 GitHub）＋**觸發後端生產部署**（reconciler 盯 origin/main）。把無所謂的雜事和唯一有生產後果的決定綁在同一個鍵，是版控不清晰的根源。三平面把它拆開：每平面一個真相、一個動詞、一條紅線。

| 平面 | 問題 | 真相 ref | 動詞 | 生產後果 |
|---|---|---|---|---|
| **develop** | 我接受了什麼 | 本地 `main` | `cutover`（worktree→本地 main，離線） | 無 |
| **backup** | 碼在機器外安全嗎 | `origin/main` | `sync`（push origin/main） | **無**（reconciler 不看 main） |
| **release** | 世界該跑什麼 | `origin/prod` + tag | `deploy`（推 origin/prod）/ `release`（統一入口） | **有（唯一）** |

**唯一碰生產 = `deploy`（backend）/ `release`（前後端統一）。** `sync` 只是備份，push 幾次都無所謂。

## 動詞對照

| 動詞 | 工具 | 讀 | 前進 | 副作用 |
|---|---|---|---|---|
| `cutover` | `ops/worktree_orchestrate.py cutover --commit` | worktree branch | 本地 `main`（ff） | 無—離線可逆 |
| `sync` | `ops/worktree_orchestrate.py sync --commit` | 本地 main | `origin/main`（守護 ff） | **零** |
| `deploy` | `ops/worktree_orchestrate.py deploy --commit` | 本地 main | `origin/prod`（守護 ff） | **生產**—reconciler 部署 |
| `tag` | `ops/release.sh tag <api\|ios> <v>` | 版號檔 | 版號 commit + `api\|ios/x.y.z` + push origin main；iOS 新版須帶 `--new-version-after-ready <previous>` | 備份/標記，無生產 |
| **`release`** | `ops/release.sh release <backend\|ios> <v>` | 版號檔、本地 main | backend：bump→tag→deploy；iOS：bump→upload→tag | **生產** |

- **`gate` / `cutover` 必須用工作樹自己那份 orchestrator**（`<worktree>/ops/worktree_orchestrate.py`）：gate 的工具以工作樹為 cwd 執行，路由規則必須同代，否則會用另一版的規則排 gate 而輸出形狀完全相同。工具自身以 sha256 比對後 refuse，判決紀錄帶 `orchestrator` 身分、cutover 一併核對。`resolve` 例外，用主 repo 那份（它會刪掉工作樹本身）。
- `deploy` 的 `--upstream` 預設 `origin/prod`；`sync` 的預設 `origin/main`。兩者共用守護引擎 `_guarded_advance`（primary 在 main、origin/<dest> 為 local 嚴格祖先、絕不 force、noop、ls-remote 事後驗證）。
- `sync` 別於 `sync-main`：`sync` 是 local→origin（備份推出）；`sync-main` 是 origin→local（追上 origin，用於 fresh clone）。
- `tag`（原名 `publish`，別名保留）push origin main = 版號 commit 的備份 + tag 標記，**非部署**。iOS 新 marketing version 的 direct tag 也必須帶 typed attestation，不能繞過 release guard。
- `release <backend|ios>` 須在 primary、on `main` 執行（發布本地主幹）。

## Release 流程

**backend**（`release backend x.y.z`）＝ `bump api`（若版號檔≠x.y.z）→ `tag api x.y.z`（commit 版號 + `api/x.y.z` + push origin main）→ `orchestrate deploy --commit`（推 origin/prod → felix reconciler 健康 gate 部署 wordnexus.lol）。dry-run 預設，`--yes` 才執行。

**ios 新版本**（`release ios x.y.z --new-version-after-ready <previous>`）＝先確認 ASC 的 previous marketing version 已完成審查 → `bump ios` → `ios_release.sh --upload`（archive + 上傳 TestFlight）→ upload 成功後才 `tag ios x.y.z`。`<previous>` 必須等於 latest local `ios/*` tag，且新版本必須嚴格遞增；這是離線 typed attestation，不會連 ASC、也不宣稱自行驗出 `READY_FOR_SALE`。upload 失敗不留下 release commit/tag/push；若版號早已 commit，成功後直接 tag current HEAD。被拒或未上架的同版重送走 `bump-build ios` + `ios_release.sh --upload`（見 ios.md），不走 release、也不得使用 attestation flag。

日常盤點：`ops/release.sh status`（各 component 待發版 commit + released gap；本地唯讀）。

## felix reconciler（release=deploy 自動收斂）

`ops/kg_reconcile.sh`（launchd `com.kg.reconcile`，90s tick，跑在 felix 專用生產 clone `~/kg-prod`）盯 **`origin/prod`**：一前進且含 backend 觸發路徑 → `git pull --ff-only origin prod` + 寫 `backend/VERSION` + `docker compose up -d --build --force-recreate` + 健康 gate（localhost + 外部 smoke + infra）；失敗自動 rollback + poison（**rollback 那次也 force-recreate**）。`--force-recreate` 不是可省的：健康 gate 比對容器自報版本，而容器自報的是 bind-mount 進去、於 import 快取的 `backend/VERSION`，只隨行程重啟改變；而 `up -d --build` 只在 image digest 或解析後 compose config hash 變了才 recreate。命中觸發卻不進 image 的改動（compose.yml 註解、Dockerfile 註解、pyproject `[tool.*]`）兩者皆不變 → 容器不重啟 → 自報舊版 → gate 判失敗 → 回滾 + poison + 告警，而 poison 只冷卻 3600 秒，**於是每小時重演一次**（IMP-0056）。非 backend 變更只 ff-only 追 repo（**刻意不寫 VERSION 游標**，見 kg_reconcile.sh §2.4 註解）。origin/prod 未 seed → 優雅 noop（不崩）。

- **desired/actual 配對**：`origin/prod` = 期望部署狀態（release 推進）；`backend/VERSION`（felix-local git sha）= 實際部署狀態（reconciler 寫）；`/api/system/info` 回報實跑版供交叉驗證。
- **生產 clone `~/kg-prod` 專屬**：compose 從 `~/kg-prod/backend` build。`~/project/kg` 是 dev/resume-only，**永不在其 backend 跑 compose**（同 project name `backend` 會劫持生產容器）。`devops.sh`/`devops_kg_safe.sh` 的 `KG_REMOTE_DIR` 預設已指 `~/kg-prod/backend`。

## felix 生產切換（首次啟用：origin/main → origin/prod 拓樸遷移）

前置：挑「零 pending backend」窗口（`git diff <deployed>..origin/main -- backend/ | grep -E "$BACKEND_TRIGGER_RE"` 為空），使切換為純機制搬遷、零功能部署。全程在 felix。

| Step | 動作 | 碰生產 |
|---|---|---|
| **P0** | 三平面 code/docs/test 落地本地 main → `sync --commit` 推 origin/main。舊 reconciler self-update 成新碼 → fetch origin/prod（未 seed）→ noop（自動部署暫停、容器不動）。P0→P2 連續做 | 否 |
| **P1** seed prod | `D=$(cat ~/project/kg/backend/VERSION)`；驗 D 為 origin/main 祖先；`git push origin origin/main:refs/heads/prod`（origin/prod=main HEAD H，backend(H)==backend(D)） | 否 |
| **P2** clone | `git clone -b prod <url> ~/kg-prod`；`cp ~/project/kg/backend/.env ~/kg-prod/backend/.env`（含 `KG_DATA_DIR=~/kg-data` 絕對路徑）、`cp -R …/certs`、`printf '%s\n' "$H" > ~/kg-prod/backend/VERSION`。先不跑 compose | 否 |
| **🚦 GO GATE** | 回報狀態 + 健康快照，取得明確 go 才進 P3 | — |
| **P3** recreate | `launchctl bootout gui/$(id -u)/com.kg.reconcile`（防 race）→ `cd ~/kg-prod/backend && docker compose up -d --build`（同 project name/container_name/volume → 原地 recreate 同一顆容器）。驗 localhost + wordnexus.lol `/api/system/info`(version==H) | **是** |
| **P4** plist | 換 `~/Library/LaunchAgents/com.kg.reconcile.plist`（路徑+KG_RECON_REPO=~/kg-prod）→ 手動 `KG_RECON_REPO=~/kg-prod ~/kg-prod/ops/kg_reconcile.sh --dry-run` **必印 noop** → `launchctl bootstrap`。觀察前幾 tick noop | 是（應 noop） |
| **P5** 純化 | `~/project/kg` 還原純 dev（由人 `git pull` 追 main，reconciler 不碰）。確認 devops footgun fix 生效 | 否 |

**P3 rollback**：新容器不健康 → 因 project name 相同，從舊 `~/project/kg/backend`（checkout H；backend(H)==backend(D)）`docker compose up -d --build` 復原同顆容器（同 volume、data 未分岔）。徹底放棄：還原 plist + bootstrap 舊 reconciler + `git push origin :prod` + `rm -rf ~/kg-prod`。
