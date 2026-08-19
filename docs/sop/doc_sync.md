<!-- doc-meta
tier: sop
authority: derived
update_trigger: docs-control-change
scope:
  - docs/
  - ops/docs_lint.sh
  - ops/docs_impact.py
  - docs/registry.yml
  - .claude/skills/kg-docs-control-plane/
  - .claude/skills/catalog.json
  - docs/sop/docs_dogfood.md
  - docs/reference/project_onboarding.md
verified_against: 8ec4780950c73b6006649c5c08e69c05962abfc1
-->
# Documentation Sync SOP

文件只記錄穩定的產品、技術、操作與安全知識；GitHub Issue／PR 記錄一次變更的討論與決策。DS（Docs Steward）對每個 PR 判斷文件 impact 並維護真正的 SoT。不要把 Issue、PR、優先序或工作樹狀態複製到 docs。

## Registry contract

`docs/registry.yml` 是文件 ownership、authority、trigger、source hint 與 agent-facing surface 的機器可讀索引。文件本身的 `doc-meta` 是局部 metadata；兩者不互相複述產品內容。

## Change flow

1. 先看 `./ops/docs_impact.py --files <changed paths>`，把輸出當候選，不當自動修改命令；若變更了 command／flag／env／schema，再以 `./ops/docs_impact.py --surface-scan '<token-or-regex>'` 查全 repo agent-facing 引用。
2. 依 registry 的 trigger 與實際 diff 判定需要同步的 SoT；若沒有語義影響，明確記錄不需同步。
3. 更新文件的最小必要段落，避免把程式碼逐字抄進 SOP。
4. 對 contract/reference/policy/runbook 檢查 `verified_against` 是可達的 code commit；不要用未驗證的未來 SHA。
5. 跑 `./ops/docs_lint.sh`；改 registry 時額外跑 `./ops/docs_lint.sh --registry` 與 coverage。
6. 文件與 code 同一 PR 交付；DS 與 CR 以 PR diff 判斷是否閉環。文件同步不建立本地工作項目、PR 狀態或另一個 review cycle。

## 新增、修改與退役

### 新增文件

只有在現有 SoT 無法承載新知識時才新增文件。先選一個唯一類型：

- `reference`：穩定產品、技術、schema、host 或 feature boundary。
- `sop`：可重跑的操作、驗證、事故或維護流程。
- `policy`：安全、批准、不可逆或保留規則。
- `runbook`：特定服務的值班／故障處理入口。

新檔必須同時具備 `doc-meta`、registry entry、owner、authority、update trigger、source hints 與至少一個可驗證的入口；沒有可重現內容就不新增文件，改寫回 GitHub Issue／PR。

### 修改文件

修改來源分兩種，不能混成一種證據：

1. **程式／設定變更**：以 code、test、PR exact HEAD 為事實，先跑 impact，再更新受影響 SoT。
2. **實測流程固化**：執行 agent 先跑出流程並保存 command、exit status、環境／device、input／fixture、artifact hash、failure signature；DS 再把穩定規則寫入 docs。聊天中的「應該可以」不是文件證據。

固化一個流程時，文件至少要回答：觸發條件、前置條件、唯一命令入口、成功判定、常見失敗與下一步、副作用／批准邊界、證據保存／TTL、owner 與 hand-off。Simulator 只是其中一個例子；換成 backend、deploy、podcast、billing 或其他流程時，替換成該 domain 的 input／environment／artifact identity 與安全 gate。若是 Simulator，還必須寫明 branch／exact HEAD、dataset／UI World SHA、Simulator UDID／lease、selector、verdict、xcresult／log／visual artifact identity，以及真機／release 證據不可由 Simulator 取代。

### 退役或刪除文件

先用 `rg` 查找全 repo 引用，再檢查 registry、agent route、workflow、script 與其他 docs 的 links。仍有歷史決策價值的檔案只能放在明確標記的 `archive`／`snapshot`，並不得出現在日常 onboarding route；沒有價值的檔案直接刪除，讓 link audit 與 docs registry coverage 證明沒有殘留。不能只把檔名改成 `legacy` 就算退役。

## 文件固化的雙代理閉環

當 Worker／Issue Solver 被要求「把流程跑通並固化」時，固定順序是：

```text
assignment
  → onboarding（執行身份）
  → branch/worktree 實測
  → exact evidence + failure classification
  → PR 描述文件 impact／候選 SoT
  → DS onboarding（pr-review）
  → docs／registry／metadata 修改
  → docs gates
  → cold-agent dogfood
  → CR review + CM merge
```

執行 agent 不得因自己成功跑過一次就自行建立「已固化」結論；DS 不得在沒有 source evidence 時猜命令或補齊流程。dogfood agent 若無法在不問作者的情況下找出正確入口、權威文件、成功判定或失敗處理，結果是 `partial`／`fail`，回到同一 PR 修正。

這個閉環適用所有「把實際流程跑通並固化」的要求；Simulator scenario 只是最容易暴露 provenance／artifact 歧義的測試樣本，不是文件系統的預設 domain。

## Generated and historical material

Generated output 必須在 registry 宣告 generator 與等值 check，產物不手改。archive、plan、spec、snapshot 是背景資料，不進日常工作路徑；若它們與現況衝突，以當前 SoT 與 code 為準。

## Failure policy

registry path 不存在、active document 未註冊、metadata 缺欄位或 verified anchor 不可達時，docs gate 應回報 ERROR。impact hint 的 WARN 需要人工判斷，不得當成已同步證據。
