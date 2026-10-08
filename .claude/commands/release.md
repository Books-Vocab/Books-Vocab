---
description: 分析已合併變更並把 backend／iOS 發布路由到 ops/release.sh
---

# Release

發布只從已合併到 GitHub `main` 的變更開始；流程實作唯一在 `ops/release.sh`，此命令不重抄細節。

先唯讀盤點：

```bash
./ops/release.sh status
```

版本號與 changelog 由 agent 自行決定（依上一個已上架 tag 之後的變更語意：新功能 = minor、只有修正 = patch、破壞性 API／資料變更 = major；`status` 建議版號僅供參考），不需使用者確認；在回報與 PR 寫明選定版本與一行理由。先 dry-run 自行驗證：

```bash
./ops/release.sh bump <api|ios> <x.y.z>
./ops/release.sh changelog <api|ios>
```

驗證後選擇對應命令（先 dry-run；owner 明確要求發版時才加 `--yes`）：

```bash
./ops/release.sh release <backend|ios> <x.y.z> [--yes]
./ops/release.sh resubmit ios [--yes]
# hand-back -> IM PR -> CM merge -> sync main 之後：
./ops/release.sh resume ios <x.y.z> <build> --pr <n> --merged-source <sha> [--yes]
./ops/release.sh finalize ios <x.y.z> <build> --pr <n> --merged-source <sha> [--yes]
./ops/release.sh shipped ios [--yes]
./ops/release.sh tag <api|ios> <x.y.z> [--yes]
```

`release`／`resubmit` 只產生 candidate（版本變更與 candidate commit），不 push、不 upload、不 deploy、不 tag。candidate 經 hand-back、IM PR、CM merge 並 sync main 後，才由 `resume`（ios）以 exact PR／merged source 證據依序做 exact ASC probe、build 不存在才 upload、tag-only 收尾；finalize 只用於 tag 補救。`resume` 僅支援 ios；backend 部署與 prod 推進屬 approved release tooling（依 `docs/sop/deploy.md`），此命令不執行。`tag` 只做版本標記。外部副作用沒有 owner 明確要求就停在 dry-run；回報只引用當次命令的 exit status、SHA／tag 與其輸出證據。
