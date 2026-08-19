<!-- doc-meta
tier: sop
authority: derived
update_trigger: review-change
scope:
  - .github/
  - .claude/agents/
  - .claude/skills/
  - docs/sop/
verified_against: 51ce9228ce64c1897850b8fcab672364b17f8731
-->
# Pull Request Review SOP

[`docs/reference/delivery_model.md`](../reference/delivery_model.md) 定義 CM、IM、Worker、Issue Solver、CR 與 DS 的責任。GitHub PR 是變更的唯一 review surface；local review output 可以輔助診斷，但不能取代 PR conversation、required checks 或 branch protection。

## PR 必須回答

- 這是 direct assignment 還是 Issue work？若有 Issue，哪個問題被處理，非目標是什麼？
- 變更涉及哪些產品面、資料／設定／安全邊界？
- 哪些測試或 checks 實際跑過，命令與 exit status 是什麼？
- 部署、migration、CloudKit、App Store 或 rollback 是否受影響？
- 若 review 不接受，最小回退或修正路徑是什麼？

PR 不是只有 code diff：CR 的 review 結論、DS 的文件 impact、Actions required checks 與 CM 的 merge 決定都應留在 GitHub PR／repository rules。它們不能被改寫成 local review cycle、merge queue 或 repo 內自製狀態。

## CR 順序

1. 先確認 PR base、HEAD、Issue 關聯與 diff 範圍。
2. 先看行為與資料安全，再看可維護性、測試 seam、文件影響與 UI／i18n 契約。
3. 對每個 blocker 指向檔案與行號，說明重現或推理依據；沒有證據就標為疑問，不寫成結論。
4. 確認 required Actions checks 是這個 PR 的新鮮結果，而不是舊 commit 的綠燈。
5. 在 GitHub PR 明確留下 approve、request changes 或 comment；不要用 repo 內自製狀態模擬審查結論。

## Required checks

`.github/workflows/pr-gate.yml` 是每個 PR 都會執行的穩定入口；其 check run `required` 是 branch protection 唯一的短 merge-blocking context。check run `confidence` 會平行收斂 backend、Linux ops shards、macOS Xcode build／unit／UI 與其他完整 checks，但不把每個 PR 綁在最慢 job 上。高風險 surface 仍可由 branch rules 要求額外 check。若 check 不適用，要在 PR 說明原因，不要刪除或繞過 check。

`confidence` 尚未完成或失敗不等於 PASS。它代表 merge 後仍需處理的驗證風險：CM 可以在 required、review 與安全條件滿足時推進下一個 PR，但不得在 confidence 未收斂前宣稱完整綠燈或執行受影響的 release／deploy。

## Blocker policy

阻塞項未修正前不能宣稱 ready。修正後必須 push 新 HEAD，讓 Actions 與 reviewer 重新針對新 diff 判斷。timeout、基線失敗、權限不足或 evidence 不完整都是偏離，不可寫成 PASS。
