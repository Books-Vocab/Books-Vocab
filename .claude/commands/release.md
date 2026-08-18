---
description: 分析已合併變更並把 backend／iOS 發布路由到 ops/release.sh
---

# Release

發布只從已合併到 GitHub `main` 的變更開始；流程實作唯一在 `ops/release.sh`，此命令不重抄細節。

先唯讀盤點：

```bash
./ops/release.sh status
```

需要版本號時，先 dry-run 並把 changelog 交給使用者確認：

```bash
./ops/release.sh bump <api|ios> <x.y.z>
./ops/release.sh changelog <api|ios>
```

確認後才選擇對應命令：

```bash
./ops/release.sh tag <api|ios> <x.y.z> --yes
./ops/release.sh release backend <x.y.z> --yes
./ops/release.sh release ios <x.y.z> --yes
./ops/release.sh resubmit ios --yes
./ops/release.sh finalize ios <x.y.z> <build> --yes
./ops/release.sh shipped ios --yes
```

`tag` 只做版本標記；backend release 受部署安全 wrapper、health gate 與 rollback SOP 保護；iOS release／resubmit 必須保留 candidate 並以 exact ASC proof 收尾。upload、部署、App Store submit 都是外部副作用，沒有明確確認就停在 dry-run。回報只引用當次命令的 exit status、SHA／tag、ASC 或線上 health 證據。
