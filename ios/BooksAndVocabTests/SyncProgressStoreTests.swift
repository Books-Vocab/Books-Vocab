import Foundation
import Testing
@testable import BooksAndVocab

/// `SyncProgressStore` 是 `backgroundSync` 與設定頁進度 UI 之間唯一的狀態載體。
/// 它有兩個不可退讓的性質，兩者都會直接被使用者看見：
///
/// 1. **單調** — 進度條與計數器都上動畫（`.contentTransition(.numericText())`），
///    任何倒退都是肉眼可見的彈回。回報來自不同 executor 的非結構化 Task，
///    到達順序沒有保證，所以守衛必須在 store 裡，而不是寄望呼叫端排序。
/// 2. **加權** — 各步驟成本差一個量級（下載單字卡 vs 查額度）。等權會讓進度條
///    在最貴的那步停住不動，這正是使用者抱怨「只有同步中…」的同一個病。
@MainActor
struct SyncProgressStoreTests {

    private func makeStore(_ ids: [SyncStepID] = SyncStepID.allCases) -> SyncProgressStore {
        let store = SyncProgressStore()
        store.begin(stepIDs: ids)
        return store
    }

    @Test("begin 建出宣告順序的步驟，全為 waiting、fraction 歸零、phase 進 running")
    func beginSeedsDeclaredSteps() {
        let store = makeStore([.push, .pull, .status])

        #expect(store.steps.map(\.id) == ["push", "pull", "status"])
        #expect(store.steps.allSatisfy { $0.status == .waiting })
        #expect(store.fraction == 0)
        #expect(store.phase == .running)
        #expect(store.steps.allSatisfy { !$0.label.isEmpty })
    }

    @Test("重新 begin 會清掉上一輪殘留，不累加")
    func beginResetsPreviousRound() {
        let store = makeStore([.push, .pull])
        store.apply(.finished(.push, status: .done, detail: "x"))
        store.finish(.completed)

        store.begin(stepIDs: [.pull])
        #expect(store.steps.map(\.id) == ["pull"])
        #expect(store.fraction == 0)
        #expect(store.phase == .running)
    }

    @Test("晚到的較小 current 被丟棄，計數器不倒退")
    func staleAdvanceIsDropped() {
        let store = makeStore([.pull])
        store.apply(.started(.pull))
        store.apply(.advanced(.pull, current: 90, total: 100, detail: "a"))
        store.apply(.advanced(.pull, current: 30, total: 100, detail: "b"))

        let pull = store.steps[0]
        #expect(pull.current == 90)
        #expect(pull.detail == "a", "被丟棄的回報不得留下它的 detail")
    }

    @Test("total 改變不構成倒退的豁免——這是舊守衛的漏洞，亂序到達時它正好放行最糟的那些事件")
    func totalChangeDoesNotExcuseARewind() {
        let store = makeStore([.pull])
        store.apply(.started(.pull))
        store.apply(.advanced(.pull, current: 90, total: 100, detail: "a"))
        store.apply(.advanced(.pull, current: 5, total: 20, detail: "late page 1"))

        #expect(store.steps[0].current == 90, "5/20 晚到會讓計數器從 90 彈回 5")
        #expect(store.steps[0].total == 100)
    }

    @Test("current 前進時 total 的更新會跟著生效")
    func advanceAcceptsGrowingCountWithNewTotal() {
        let store = makeStore([.pull])
        store.apply(.started(.pull))
        store.apply(.advanced(.pull, current: 0, total: 0, detail: "connecting"))
        store.apply(.advanced(.pull, current: 5, total: 20, detail: "merging"))

        #expect(store.steps[0].current == 5)
        #expect(store.steps[0].total == 20)
    }

    @Test("current 超過 total 時在入口就夾住，不讓 view 印出 90/20")
    func currentIsClampedToTotal() {
        let store = makeStore([.pull])
        store.apply(.started(.pull))
        store.apply(.advanced(.pull, current: 90, total: 20, detail: ""))

        #expect(store.steps[0].current == 20)
    }

    @Test("第一個終態說了算：成功收尾後晚到的 error 不得把綠翻紅")
    func firstTerminalWins() {
        let store = makeStore([.pull])
        store.apply(.started(.pull))
        // 真實序列：pullCardsToLocal 內部在單字卡 merge 成功後發 done，
        // 接著字典卡投影拋非 404，外層的失敗補救又發一次 error。
        store.apply(.finished(.pull, status: .done, detail: "同步 6 筆"))
        store.apply(.finished(.pull, status: .error, detail: "伺服器錯誤"))

        #expect(store.steps[0].status == .done, "卡片已經寫進本地庫了，那一列不該翻紅")
        #expect(store.steps[0].detail == "同步 6 筆")
    }

    @Test("已終結的步驟不會被晚到的 advanced 復活")
    func terminalStepIsNotRevivedByLateAdvance() {
        let store = makeStore([.pull])
        store.apply(.started(.pull))
        store.apply(.advanced(.pull, current: 10, total: 20, detail: ""))
        store.apply(.finished(.pull, status: .done, detail: "done"))
        store.apply(.advanced(.pull, current: 12, total: 20, detail: "late"))

        #expect(store.steps[0].status == .done, "綠勾被打回轉圈，而 endTime 還留著")
        #expect(store.steps[0].detail == "done")
    }

    @Test("started 會把該步驟歸零，讓重跑不受上一段的守衛擋住")
    func startedResetsCounters() {
        let store = makeStore([.pull])
        store.apply(.started(.pull))
        store.apply(.advanced(.pull, current: 90, total: 100, detail: "a"))
        store.apply(.started(.pull))

        #expect(store.steps[0].current == 0)
        #expect(store.steps[0].status == .running)
    }

    @Test("fraction 依權重推進：貴的步驟完成推得比便宜的多")
    func fractionIsWeighted() {
        let cheap = makeStore([.pull, .status])
        cheap.apply(.finished(.status, status: .done, detail: ""))
        let afterCheap = cheap.fraction

        let costly = makeStore([.pull, .status])
        costly.apply(.finished(.pull, status: .done, detail: ""))
        let afterCostly = costly.fraction

        #expect(afterCostly > afterCheap)
        #expect(abs((afterCheap + afterCostly) - 1.0) < 1e-9, "兩步驟的權重份額必須剛好瓜分完整條進度")
    }

    @Test("running 步驟的 current/total 會即時反映在 fraction 上")
    func fractionTracksRunningCounts() {
        let store = makeStore([.pull])
        store.apply(.started(.pull))
        let atStart = store.fraction
        store.apply(.advanced(.pull, current: 50, total: 100, detail: ""))
        let atHalf = store.fraction

        #expect(atStart > 0, "步驟一開始就該給起步額度，否則長步驟期間進度條完全不動")
        #expect(atHalf > atStart)
        #expect(atHalf < 1.0)
    }

    @Test("fraction 單調不減，即使步驟被 .started 合法重跑")
    func fractionNeverDecreases() {
        let store = makeStore([.pull, .status])
        store.apply(.finished(.pull, status: .done, detail: ""))
        let peak = store.fraction
        // `.started` 是唯一的合法重設路徑（retry），列本身確實會回到 running——
        // 但整輪「已經走了多遠」不該倒退。
        store.apply(.started(.pull))

        #expect(store.fraction >= peak)
        #expect(store.steps[0].status == .running, "retry 必須看得出來在重跑")
    }

    @Test("終態三種都算完成：done / skipped / error 都把該步驟的權重計滿")
    func terminalStatusesCountAsComplete() {
        for status in [PipelineStep.StepStatus.done, .skipped, .error] {
            let store = makeStore([.pull, .status])
            store.apply(.finished(.pull, status: status, detail: ""))
            #expect(store.steps[0].status == status)
            // 期望值寫字面量而不是從 SyncStepID.weight 推導：從實作自己的表推導
            // 等於整張權重表換掉這條也不會紅。pull=4、status=1 → 4/5。
            #expect(abs(store.fraction - 0.8) < 1e-9)
        }
    }

    @Test("finish(.completed) 收到 1；跑過的收成 done，從未開始的收成 skipped 而不是假綠")
    func completedDistinguishesRanFromNeverRan() {
        let store = makeStore([.push, .pull, .podcast])
        store.apply(.finished(.push, status: .done, detail: ""))
        store.apply(.started(.pull))          // 跑了但沒發收尾事件
        // .podcast 從頭到尾沒被回報
        store.finish(.completed)

        #expect(store.phase == .completed)
        #expect(store.fraction == 1.0)
        #expect(store.steps[1].status == .done)
        #expect(store.steps[2].status == .skipped, "宣告了卻整輪沒跑的步驟打綠勾＝對使用者說謊")
    }

    @Test("空步驟清單完成時 fraction 仍是 1，不會停在 0%")
    func completedWithNoStepsStillReadsFull() {
        let store = SyncProgressStore()
        store.begin(stepIDs: [])
        store.finish(.completed)

        #expect(store.fraction == 1.0)
    }

    @Test("finish(.failed) 不偽造完成：未跑完的步驟維持原狀，fraction 不強制拉滿")
    func failedKeepsStepsHonest() {
        let store = makeStore([.push, .pull])
        store.apply(.finished(.push, status: .error, detail: "boom"))
        store.finish(.failed)

        #expect(store.phase == .failed)
        #expect(store.steps[1].status == .waiting)
        #expect(store.fraction < 1.0)
    }

    @Test("未宣告的步驟事件被忽略，不會憑空長出一列")
    func unknownStepEventsAreIgnored() {
        let store = makeStore([.pull])
        store.apply(.started(.podcast))
        store.apply(.finished(.podcast, status: .done, detail: ""))

        #expect(store.steps.count == 1)
        #expect(store.fraction == 0)
    }

    @Test("每個 SyncStepID 都有非空 label 與正權重")
    func everyStepIDIsPresentable() {
        for id in SyncStepID.allCases {
            #expect(id.weight > 0)
            #expect(!id.label.isEmpty)
        }
    }

    @Test("reset 回到未開始狀態，UI 收合後不留殘影")
    func resetClearsEverything() {
        let store = makeStore([.pull])
        store.apply(.finished(.pull, status: .done, detail: ""))
        store.finish(.completed)
        store.reset()

        #expect(store.steps.isEmpty)
        #expect(store.phase == .ready)
        #expect(store.fraction == 0)
    }

    @Test("同步面板 visibility 同時反映同步旗標與 steps identity")
    func progressPanelVisibilityTracksSyncAndDeclaredSteps() {
        let store = SyncProgressStore()

        #expect(!SettingsSyncProgressPanel.isVisible(isSyncing: true, steps: store.steps))

        store.begin(stepIDs: [.push])

        #expect(SettingsSyncProgressPanel.isVisible(isSyncing: true, steps: store.steps))
        #expect(!SettingsSyncProgressPanel.isVisible(isSyncing: false, steps: store.steps))
    }
}
