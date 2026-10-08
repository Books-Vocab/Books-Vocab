---
name: "source-command-release"
description: "把已合併到 main 的 backend／iOS 變更路由到 ops/release.sh，保留版本、外部發布與 rollback 安全邊界"
---

# source-command-release

`ops/release.sh` 是唯一發布入口；本 skill 只做路由、確認與 hard-stop，不重抄腳本實作。

## 標準前提

變更先經 direct assignment 或 GitHub Issue（若需要規劃）、branch、PR、Actions／CR／DS review，合併到受保護的 `main`；release 只處理已合併主幹。先讀 [`docs/reference/delivery_model.md`](../../../docs/reference/delivery_model.md)：

```bash
./ops/release.sh status
```

版本號、changelog、外部上傳或生產部署都不能由 agent 自行猜測。需要改版時先跑 dry-run，將計畫交給使用者確認：

```bash
./ops/release.sh bump <api|ios> <x.y.z>
./ops/release.sh changelog <api|ios>
```

## 命令選擇

- `tag`：只建立版本標記，不部署；無 `--yes` 不寫入。
- `release backend|ios <version>`：只產生 candidate（版本變更與 candidate commit），不 push、不 upload、不 deploy、不 tag；之後走 hand-back -> IM PR -> CM merge -> sync main。
- `resubmit ios`：同 marketing version 取得 ASC 對帳後的新 build candidate；同樣只產生 candidate，不 push、不 upload、不 deploy、不 tag。
- `resume ios <version> <build> --pr <n> --merged-source <sha>`：merged main 上的外部發布入口；先 dry-run，`--yes` 後依序 exact ASC probe、build 不存在才 upload、tag-only 收尾。只支援 ios；backend 部署與 prod 推進屬 approved release tooling（`docs/sop/deploy.md`）。
- `finalize ios <version> <build> --pr <n> --merged-source <sha>`：tag 補救；重查 exact ASC 證據並封版，不 archive、不 upload。
- `shipped ios`：只在 ASC 確認 App Store 已上架後建立上架標記；查不到唯一事實就拒絕猜測。

所有有外部副作用的命令先 dry-run，只有使用者明確確認後才加 `--yes`。不可把文件、dry-run、本地 archive 或猜測當成部署／TestFlight／App Store 成功證據。

## iOS hard stops

送審前依 `docs/sop/ios.md` 執行 workflow、App Review evidence 與 release gate；任一 BLOCK 只能查詢狀態或補 typed evidence，不可用手工 GUI 繞過 gate。`resume`／`finalize` 必須帶 exact `--pr <n> --merged-source <sha>`，且 proof 必須是當下 exact `(version, build)` ASC 輸出。

## 回報

只回報當次命令的 exit status、exact SHA／tag、ASC 或線上 health 證據、偏離與 blocker。生產部署、rollback、App Store submit 等不可逆動作若沒有明確授權，停在 dry-run。
