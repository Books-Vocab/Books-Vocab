<!-- doc-meta
tier: sop
authority: derived
update_trigger: review-change
scope:
  - .github/
  - .claude/agents/
  - .claude/skills/
  - ops/agent_onboard.py
  - ops/context_plane.json
  - ops/skill_route.py
  - docs/reference/project_onboarding.md
  - docs/sop/
verified_against: 5b5ac2fa158ec2f9508c0befa835720009a60fe5
-->
# Pull Request Review SOP

[`docs/reference/delivery_model.md`](../reference/delivery_model.md) 定義 CM、IM、Worker、Issue Solver、CR 與 DS 的責任。GitHub PR 是變更的唯一 review surface；local review output 可以輔助診斷，但不能取代 PR conversation、required checks 或 branch protection。

## Independent agent review boundary

Collaborator approval 與獨立 agent review 都是品質與風險的 review evidence，不是單獨的 merge 授權。`agent-review` 由受信任的 base-branch workflow 產生 exact-head、可追溯的品質觀測；它目前是 optional advisory check，不是 repository ruleset 的 hard gate。只有 GitHub `required`、exact typed tuple、branch rules、mergeability 與明確安全 hold 才參與 merge admission。

`agent-review` 的最低契約如下：

- workflow 使用 `pull_request_target`／review events，從 trusted base 執行，不 checkout 或執行 PR 程式碼；
- review 或 reaction 必須由已辨識的 independent reviewer identity 提供，且綁定目前 PR HEAD；舊 HEAD 的證據不算；
- P0、P1、security hold 使 check 失敗；P2、advisory 或 baseline observation 只能作為 review warning；
- check 必須以 `checks:write` 建立在 exact PR HEAD，並保留 reviewer、HEAD、結論與 blocker evidence；
- shell caller、PI、CM 若讀取此 check，仍須保留 exact conclusion、reviewer、HEAD 與 blocker evidence；不得以 workflow exit code、local review 摘要或 self-approval 偽造 review 結論。
- `agent-review` 缺失、失敗、延遲或成功都不會單獨阻塞 queue／merge；若 evidence 明確指出 P0、P1 或 security，必須另行寫成 durable typed hold／label，該 hold 才是硬性阻塞來源。
- repository ruleset 的 required contexts 應維持只有短 `required`。這是降低無意義的 transport gate，不是移除 review；agent-review 仍可用來改善品質與發現風險。

## Bounded review-evidence preflight

`ops/review_preflight.py` 是本機的 bounded、read-only evidence preflight。它只讀取 caller 提供的 JSON，輸出一份 `kg.review.preflight.v1` 摘要；不呼叫 GitHub、不建立或修改 review／check、不寫 backlog 或 status DB，也不執行 merge、release 或 production mutation。它協助 caller 在把證據交給 PR／CM 流程前分辨資料缺口，但不是另一個 review surface。

輸入 schema 是 `kg.review.evidence.v1`，最小形狀如下；`pr`、`head`、`reviewer` 與 `deadline` 都是 opaque non-empty strings，只做 presence 與 exact equality，不解析、排序、截斷或正規化：

```json
{
  "schema": "kg.review.evidence.v1",
  "source": {"status": "ok"},
  "target": {"pr": "<opaque-pr>", "head": "<opaque-head>"},
  "required_snapshot": {
    "status": "SUCCESS",
    "pr": "<opaque-pr>",
    "head": "<opaque-head>"
  },
  "review": {
    "reviewer": "<opaque-reviewer>",
    "deadline": "<opaque-deadline>",
    "receipt": {
      "schema": "kg.review.receipt.v1",
      "status": "PASS",
      "pr": "<opaque-pr>",
      "head": "<opaque-head>",
      "reviewer": "<opaque-reviewer>",
      "deadline": "<opaque-deadline>",
      "substantive": true,
      "evidence": [{"kind": "<opaque-kind>", "detail": "<substantive-detail>"}]
    }
  }
}
```

判讀順序與 verdict 固定如下：

- `source.status=timeout` 回 `review_service_timeout`；`source.status=failure`、source 缺失／未知、輸入 JSON／schema／target 無法解析回 `source_failure`。兩者不能折疊成 `BLOCK` 或 `PASS`。
- `required_snapshot` 缺失或欄位不完整回 `BLOCK`；status 不是 `SUCCESS`，或其 exact PR／HEAD 與 target 不同，回 `BLOCK`／`required_snapshot_stale`。
- receipt 缺失或不完整、非 substantive、非 `PASS`，或 PR／HEAD／reviewer／deadline 任一不 exact，回 `BLOCK`，並在 `blockers` 保留具體 reason code（例如 `exact_head_mismatch`、`receipt_incomplete`）。
- 只有 required snapshot 對 exact target，且 receipt 同時具備 `kg.review.receipt.v1`、substantive evidence、`PASS` 與 exact PR／HEAD／reviewer／deadline，才回 `PASS`。

呼叫方式：

```bash
./ops/review_preflight.py --input <evidence.json> --json
cat <evidence.json> | ./ops/review_preflight.py --json
```

命令永遠只讀 input、永遠輸出 JSON；exit code 是 `PASS=0`、`BLOCK=1`、`review_service_timeout=2`、`source_failure=3`。輸出中的 `authority` 會明示 GitHub review、required checks 與 CM merge authority 未被取代，caller 仍必須回到 PR 的 exact HEAD／required／review／branch rules 流程。

CR 進場先執行 `./ops/agent_onboard.py --identity CR --intent review --entry pr-review --evidence '<JSON object with GitHub PR, exact HEAD, required checks>' --json`。只有 `status=ready` 才能載入 `code-review` skill 與本 SOP；這一步確認的是上下文，不是 merge 權限。

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
5. 在 GitHub PR 明確留下 approve、request changes 或 comment；若使用 `agent-review`，則由 trusted workflow 留下 exact-head check，不能用 repo 內自製狀態模擬審查結論。它是可選品質證據，不是額外的 required context。

## Required checks

`.github/workflows/pr-gate.yml` 是每個 PR 都會執行的穩定基線（workflow `pr-gate` 的 `required` check run）；其餘 `.github/workflows/` 依變更面提供 backend、UI、design-system、LLM 與 ops checks。高風險 surface 由 branch rules 要求額外 check。若 check 不適用，要在 PR 說明原因，不要刪除或繞過 check。

`gate` 的 required merge gate 與 `confidence` 的 nonblocking fan-out 判讀，以 [`delivery_model.md` 的 Required merge gate 與 confidence fan-out](../reference/delivery_model.md#required-merge-gate-confidence-fan-out) 為唯一 SoT；confidence 未完成或失敗時，不得宣稱完整綠或進受影響 release／deploy。

## Blocker policy

阻塞項未修正前不能宣稱 ready。修正後必須 push 新 HEAD，讓 Actions 與 reviewer 重新針對新 diff 判斷。timeout、基線失敗、權限不足或 evidence 不完整都是偏離，不可寫成 PASS。
