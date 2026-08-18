<!-- doc-meta
tier: sop
authority: derived
update_trigger: docs-control-change
scope:
  - docs/
  - ops/docs_lint.sh
  - ops/docs_impact.py
  - docs/registry.yml
verified_against: 202119f69a4be584f6bacf80b11a12a7bb8579c5
-->
# Documentation Sync SOP

文件只記錄穩定的產品、技術、操作與安全知識；GitHub Issue／PR 記錄一次變更的討論與決策。不要把 Issue、PR、優先序或工作樹狀態複製到 docs。

## Registry contract

`docs/registry.yml` 是文件 ownership、authority、trigger、source hint 與 agent-facing surface 的機器可讀索引。文件本身的 `doc-meta` 是局部 metadata；兩者不互相複述產品內容。

## Change flow

1. 先看 `./ops/docs_impact.py --files <changed paths>`，把輸出當候選，不當自動修改命令。
2. 依 registry 的 trigger 與實際 diff 判定需要同步的 SoT；若沒有語義影響，明確記錄不需同步。
3. 更新文件的最小必要段落，避免把程式碼逐字抄進 SOP。
4. 對 contract/reference/policy/runbook 檢查 `verified_against` 是可達的 code commit；不要用未驗證的未來 SHA。
5. 跑 `./ops/docs_lint.sh`；改 registry 時額外跑 `./ops/docs_lint.sh --registry` 與 coverage。
6. 文件與 code 同一 PR 交付；reviewer 以 diff 判斷是否閉環。

## Generated and historical material

Generated output 必須在 registry 宣告 generator 與等值 check，產物不手改。archive、plan、spec、snapshot 是背景資料，不進日常工作路徑；若它們與現況衝突，以當前 SoT 與 code 為準。

## Failure policy

registry path 不存在、active document 未註冊、metadata 缺欄位或 verified anchor 不可達時，docs gate 應回報 ERROR。impact hint 的 WARN 需要人工判斷，不得當成已同步證據。
