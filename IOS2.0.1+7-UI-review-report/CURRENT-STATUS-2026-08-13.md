# iOS 2.0.1 UI review：現行控制狀態

日期：2026-08-16

本檔只描述目前可交付的控制面。原始輸入是同目錄的 PDF 與 `p1.PNG`–`p15.PNG`；圖片是需求參照，不是自動產生測試數量的規則。

## 現行判定

- 控制面：5 clusters、15 requirements、16 個 selector bindings；目前 run-plan 對應 28 個 unique XCTest selectors。
- matrix：P1–P15 目前全部為 `pending`。現有 selector-level 結果與舊 source HEAD 不足以形成目前 requirement 的完整 required/counterexample state union，因此不寫入 verified。
- 本輪依使用者授權不執行 build、Simulator 或 UITest；這是執行範圍豁免，不是產品測試通過證據。
- 目前不能宣稱 P1–P15 完成、Gate 通過或可合併。

## 報告真正要求的重構

15 張圖實際聚合成五類跨頁問題：

1. Dictionary：lookup、typed sense、provenance、materialization 必須由同一狀態模型驅動。
2. Reader：TOC 成功邊界、settings round-trip、viewport／theme／progress／loading／retry 必須是可重播狀態機。
3. Explore／Overview：loading、empty、retry、calendar 與 forecast 必須分離資料狀態和視覺投影。
4. Vocabulary／Review Card：rich fixture、搜尋／review CTA、長內容與 grading toolbar 必須驗證實際資料鏈。
5. Settings／Sync：preference、sync、error、retry 與 reset boundary 必須可觀察、可恢復。

因此本任務不是逐張圖片加 padding 或新增 selector，而是重構資料／狀態／元件／互動時序，再以 UI World 與狀態矩陣驗證。

## UITest matrix 審查結論

目前 target 有 26 個 concrete UITestCase 類別、55 個 `test...` 方法；matrix 只引用 28 個 unique selectors，另有 27 個未被報告矩陣引用。這些數字不是獨立使用者流程數量。

- Explore matrix 曾直接呼叫公開 XCTest 方法，造成 focused flow 與 matrix flow 重跑；應由 private scenario helper 供唯一 evidence owner 使用。
- Overview 的 populated stats 與 vocabulary projection 曾由多個 selector 重複執行；應收斂為 canonical flow 加 state matrix。
- Bookshelf、Notebook、Settings smoke 有入口或空狀態重疊，應保留唯一 owner。
- Dictionary 的 loading／partial／retry／offline／error 是有效狀態，但應由 canonical flow 加 typed state matrix 表達，不再按圖片拆 selector。
- launch argument、fixture decode、release preflight、backend/account rejection 等沒有產品 UI 操作的契約，應與 UI flow 分開計數。

## 現行 agent 工具契約

- 一般 `ios_test` 是 behavior-only；只有明確視覺檢查才啟用 capture。
- Catalog／Simulator capture 預設寫入有 TTL 的系統暫存；單次視覺 run 的 PNG、MP4、HTML、xcresult 只服務該次 agent 觀察。
- 只有報告或 hand-off 明確需要時，才用 `--retain` 將必要二進位提升至 `build/ios-report/retained/`；永久保存的是 fixture、selector、matrix、verdict/provenance 與 review receipt。
- run 必須帶 run ID、PID、owner、worktree、HEAD、dataset、開始時間與 expiry；完成標記 success/failure/abandoned，cleanup 先確認 runner／xcodebuild／consumer／lock 均不存在。
- matrix 只有在同一 source HEAD 上完成 machine contract、狀態 union、視覺 attestation 與 receipt 後才可寫入 verified。

## 目前最小差距

1. source／fixture／selector／matrix 結構已可供重播，但目前沒有本輪 fresh exact-head UI evidence。
2. 既有 selector PASS 只能作歷史或 targeted 診斷，不能代替完整 requirement coverage。
3. 下一次真正取證時，只需從現行 run helper 產生暫存 run；完成後保留 compact receipt，除非明確 hand-off，不保存圖片或影片。

## 工作樹狀態

本次整理只在目前整合中的 root `main` 工作副本進行；未建立新 worktree／branch，亦未觸碰使用者指定的獨立工作樹或 dirty debug 工作樹。當前工作副本仍有本輪未提交變更，不能宣稱 clean 或已落到 remote。
