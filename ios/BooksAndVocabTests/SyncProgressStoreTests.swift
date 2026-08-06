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

    @Test("total 改變代表換了一批工作，較小的 current 這時必須被接受")
    func advanceAcceptedWhenTotalChanges() {
        let store = makeStore([.pull])
        store.apply(.started(.pull))
        store.apply(.advanced(.pull, current: 90, total: 100, detail: "a"))
        store.apply(.advanced(.pull, current: 5, total: 20, detail: "next page"))

        #expect(store.steps[0].current == 5)
        #expect(store.steps[0].total == 20)
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

    @Test("fraction 單調不減，即使步驟狀態被亂序覆寫")
    func fractionNeverDecreases() {
        let store = makeStore([.pull, .status])
        store.apply(.finished(.pull, status: .done, detail: ""))
        let peak = store.fraction
        store.apply(.started(.pull))

        #expect(store.fraction >= peak)
    }

    @Test("終態三種都算完成：done / skipped / error 都把該步驟的權重計滿")
    func terminalStatusesCountAsComplete() {
        for status in [PipelineStep.StepStatus.done, .skipped, .error] {
            let store = makeStore([.pull, .status])
            store.apply(.finished(.pull, status: status, detail: ""))
            #expect(store.steps[0].status == status)
            #expect(store.fraction == SyncStepID.pull.weight
                / (SyncStepID.pull.weight + SyncStepID.status.weight))
        }
    }

    @Test("finish(.completed) 把 fraction 收到 1，殘留未回報的步驟收成 done")
    func completedFinishesEveryStep() {
        let store = makeStore([.push, .pull])
        store.apply(.finished(.push, status: .done, detail: ""))
        store.finish(.completed)

        #expect(store.phase == .completed)
        #expect(store.fraction == 1.0)
        #expect(store.steps.allSatisfy { $0.status == .done })
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
}
