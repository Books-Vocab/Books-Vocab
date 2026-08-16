<!-- doc-meta
tier: archive
authority: frozen
update_trigger: none
scope:
  - ops/
  - docs/
verified_against: frozen
-->
# iOS 視覺觀察工具退役記錄（2026-08-16）

本檔是歷史記錄，不是現行流程入口。現行 agent 不應依本檔恢復任何已淘汰的常駐視覺產物模型。

## 被淘汰的模型

曾經存在一套把 UITest screenshot、contact sheet、HTML、MP4、xcresult 集中留在 repo `build/snapshots/` 下的 workspace／gallery 模型，並以跨 run index、Catalog snapshot／review 入口及批次 asset CLI 尋找「最新」畫面。這套模型也曾讓一般 UI test 執行自動產生大量二進位檔案。

它被淘汰的原因是：

- 人類使用者的主要互動方式是直接操作 app，不需要維護一個靜態 UI asset 展示層。
- agent 需要的是指定 UI World 在真實 Simulator window 的即時觀察能力，不是累積圖片檔案。
- 跨 run 的最新指標、重複 snapshot、永久 video 與死掉的 workspace index 增加認知負擔，也造成 `build/` 與暫存區無界膨脹。
- selector、fixture、狀態矩陣與 provenance receipt 才是可重播、可審查、可交付的控制面；二進位畫面不是第二份 SoT。

## 淘汰後的替代模型

現行流程只保留以下責任：

1. UI World／fixture／selector／matrix 契約進版控，作為 agent 的可重播工具。
2. Catalog 在需要時租 disposable Simulator，capture 預設寫入帶 TTL 的系統暫存路徑，session 結束後回收。
3. 視覺 UITest 由單次 run 建立 run-scoped bundle；PNG、MP4、HTML、xcresult 只在該 run 存活期間供 agent 讀取。
4. 只有報告或正式 hand-off 明確需要二進位證據時，才以 `--retain` 提升到 `build/ios-report/retained/`，並以小型 verdict／provenance／review receipt 綁定來源。
5. cleanup 必須先確認 PID、runner、xcodebuild、consumer 與 lock 都不存在，再按 manifest／TTL 回收；不得以「最新檔案」或目錄掃描推導有效性。

## 同批廢棄物登記：web／Chrome parity subtree

`frozen/2026-06-14-web-chrome-parity/` 是另一棵已無現行 owner 的 web pilot、Chrome extension 與 parity 工具樹；本次一併從現行 source 移除。它包含 653 個 tracked files、約 6.7M 的程式與測試，不是現行 KG app 的必要 runtime。

唯一仍被現行 `marketing_demo` Podcast UI fixture 使用的 `podcast_demo.mp3` 已搬到 `ops/fixtures/assets/podcast_demo.mp3`，並同步 baseline 與 generated manifest；其餘 subtree、舊 parity 入口與依附的生成物均不保留。Git 歷史仍可追溯被移除的完整 subtree，但現行 agent 不應從歷史搬回 parity 入口。

同批已回收 repo 內舊的 Catalog／gallery／UITest 生成物；這些不是 source、fixture 或 receipt，均可由現行 ephemeral workflow 重建，不列入任何 current matrix。

## 歷史資料處置

過去產生的 bundle、snapshot、影片與 HTML 只可作為歷史盤點材料；沒有同一 source HEAD、UI World、device、exact selector、machine contract 與 visual attestation 的資料，不得重新寫入現行矩陣，也不得被稱為目前通過。保留、移除或回收歷史二進位資料須依當次 storage cleanup receipt 處理，不由本檔自動授權刪除。

本檔不列入日常 workflow、report matrix 或 agent hand-off；它唯一用途是解釋為何現行入口不再提供上述模型。
