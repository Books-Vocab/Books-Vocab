//
//  SyncProgress.swift
//  Books & Vocab
//
//  同步進度的共用模型與 store。
//
//  型別（`PipelineStep` / `SyncPhase`）原本住在 `SyncCoordinator.swift`，那裡是
//  詞庫頁那條獨立的手寫同步管線。設定頁的「同步中…」要細分成逐步狀態時需要同一組
//  型別與同一套呈現（`SyncPresenter.stepRow` / `statusSymbol`），把它們留在
//  coordinator 裡等於逼第二個消費者去 import 一條它不使用的管線。搬到這裡是純位移，
//  語意一個字沒動。
//
//  `SyncProgressStore` 則是新的：`backgroundSync` 與設定頁進度 UI 之間的狀態載體。
//  它刻意不 import SwiftUI —— 動畫由 view 端以 `.animation(_:value:)` 施加，
//  model 不決定觀感，也讓這裡整份可單元測試。
//

import Foundation

// MARK: - Pipeline model（自 SyncCoordinator.swift 搬移，語意未變）

struct PipelineStep: Identifiable, Sendable {
    let id: String
    let label: String
    var status: StepStatus = .waiting
    var current: Int = 0
    var total: Int = 0
    var detail: String = ""
    var startTime: Date?
    var endTime: Date?
    /// 這一步在整條進度條裡佔的份額。預設 1 = 等權，供
    /// `SyncCoordinator` 那條既有管線沿用原本的等權行為。
    var weight: Double = 1

    enum StepStatus: Sendable {
        case waiting
        case running
        case retry
        case done
        case skipped
        case error

        /// 已經不會再動的狀態。三者都把該步驟的權重計滿——失敗也是「這步結束了」，
        /// 讓進度條卡在 80% 不動並不會讓失敗更明顯，只會讓成功的那條看起來壞掉。
        var isTerminal: Bool {
            switch self {
            case .done, .skipped, .error: return true
            case .waiting, .running, .retry: return false
            }
        }
    }
}

enum SyncPhase: Sendable {
    case ready
    case running
    case completed
    case failed
}

// MARK: - backgroundSync 的步驟身分

/// `backgroundSync`（＋設定頁 resync 尾端的額度/連線檢查）會回報的步驟。
///
/// 粒度刻意停在「使用者看得懂且會分別失敗」的邊界上：`pushReviewStates` 與
/// `pushReviewEvents` 併發跑、一起成功一起失敗，拆成兩列只會多一列相同的字。
enum SyncStepID: String, Sendable, CaseIterable {
    /// 送出本機的複習狀態與複習事件（兩者併發）。
    case push
    /// 拉回單字卡。唯一有真實 current/total 可回報的步驟。
    case pull
    /// 拉回字典卡投影。**序列跟在 `pull` 之後**，理由見 `KGService+Sync.swift`。
    case dictionary
    /// 拉回伺服器端的複習事件。
    case reviewEvents
    /// 更新 Podcast 目錄（Release 由 `KGFeatureFlags.podcastEnabled` 關掉，不宣告此步）。
    case podcast
    /// 今日額度 + 連線檢查。兩者都是唯讀且瞬間完成，合成一列。
    case status

    var label: String {
        switch self {
        case .push:         return L10n.string("送出複習紀錄")
        case .pull:         return L10n.string("下載單字卡")
        case .dictionary:   return L10n.string("下載字典卡")
        case .reviewEvents: return L10n.string("下載複習紀錄")
        case .podcast:      return L10n.string("更新 Podcast 目錄")
        case .status:       return L10n.string("額度與連線")
        }
    }

    /// 相對成本。**這是量級估計，不是實測值**——手上唯一的實測是整輪切分
    /// （2026-08-06 生產：整輪 7.55s、podcast 段 6.08s，故 vocab 管線 ≈ 1.5s），
    /// 沒有細到各 leg 的分解。權重只需要「別讓最貴的那步在條上跟最便宜的一樣寬」，
    /// 精確到小數點沒有意義；真正的細緻度來自 `pull` 步驟回報的 current/total。
    var weight: Double {
        switch self {
        case .push:         return 1
        case .pull:         return 4
        case .dictionary:   return 2
        case .reviewEvents: return 1
        case .podcast:      return 2
        case .status:       return 1
        }
    }
}

/// 一則進度回報。`Sendable` 是硬需求：`backgroundSync` 在任意 executor 上跑，
/// 事件要跨到 MainActor 的 store。
enum SyncProgressEvent: Sendable, Equatable {
    /// 該步驟開始。會把 current/total 歸零，讓重跑不被單調守衛擋住。
    case started(SyncStepID)
    /// 進行中的計數更新。
    case advanced(SyncStepID, current: Int, total: Int, detail: String)
    /// 該步驟結束（`status` 須為終態）。
    case finished(SyncStepID, status: PipelineStep.StepStatus, detail: String)
}

/// `backgroundSync` 的回報縫。預設 nil = 完全沒有進度回報，所有既有 caller 與
/// 測試因此零影響。
typealias SyncProgressReporting = @Sendable (SyncProgressEvent) -> Void

/// 一輪 `backgroundSync` 的結果。
///
/// **為什麼需要這個型別，而不是讀 `lastBackgroundSyncError`**：那個欄位是四個
/// trigger 共用的全域，它答不出「**這一輪**發生了什麼」。兩個具體的錯法：
/// - scenePhase 觸發的同步正在跑（一輪約數秒），使用者這時打開設定頁按同步 →
///   `claimBackgroundSync()` 失敗、整支在重置該欄位之前就 return。呼叫端讀到的是
///   **上一輪**留下的值：nil 就報成功（一輪什麼都沒做的同步顯示 100% 完成），
///   非 nil 就報失敗。
/// - 中途取消刻意讓該欄位維持 nil（「既非成功也非失敗」），呼叫端一樣會讀成成功。
enum SyncRoundOutcome: Sendable, Equatable {
    /// 整輪跑完，每一條腿都沒有真正的失敗。
    case completed
    /// 至少一條腿真的失敗了（不含取消）。
    case failed
    /// 這一輪什麼都沒做——離線、被另一輪佔著 claim、或中途取消。
    /// **不是成功也不是失敗**：UI 該直接收合，不宣稱任何事。
    case didNotRun
}

// MARK: - Store

/// 同步進度的唯一狀態載體。
///
/// **為什麼不掛在 `KGService` 上**：`KGService` 是 `@Observable` 但不是
/// `@MainActor`，而 `backgroundSync` 已經在任意 executor 上寫它的 observable
/// 屬性。再往上疊高頻寫入會踩本專案已取證的 P0——`@Observable` 在 render path
/// 被 mutate 造成 21,311 次求值迴圈與裝置凍結
/// （`docs/archive/review_flip_forensic_audit_2026-06.md`）。高頻 observable 的
/// 既有正解是把它隔離進葉節點（`PodcastProgressTicker` 模式），此 store 就是
/// 那個葉節點的狀態來源，並以 `@MainActor` 從型別層擋掉跨執行緒寫入。
@Observable @MainActor
final class SyncProgressStore {

    /// 步驟起跑時就給的額度。若讓 running 步驟從 0 算起，進度條會在最長的那步
    /// 期間完全不動——那正是使用者抱怨「只有同步中…」的同一種無資訊感。
    static let runningFloor: Double = 0.15

    private(set) var steps: [PipelineStep] = []
    private(set) var phase: SyncPhase = .ready
    /// 0...1。**單調不減**（見 `recomputeFraction`）。
    private(set) var fraction: Double = 0

    func begin(stepIDs: [SyncStepID]) {
        steps = stepIDs.map {
            PipelineStep(id: $0.rawValue, label: $0.label, weight: $0.weight)
        }
        phase = .running
        fraction = 0
    }

    func apply(_ event: SyncProgressEvent) {
        switch event {
        case .started(let id):
            mutate(id) { step in
                step.status = .running
                step.current = 0
                step.total = 0
                step.detail = ""
                step.endTime = nil
                if step.startTime == nil { step.startTime = Date() }
            }

        case .advanced(let id, let current, let total, let detail):
            mutate(id) { step in
                // 兩道守衛，對應兩種「回報晚到」的後果。回報來自非結構化 Task，
                // 到達順序沒有保證（呼叫端若走 AsyncStream 就有序，但 store 不能
                // 假設呼叫端做對了）。
                //
                // 1. 已終結的步驟不得復活。晚到的 advanced 會把綠勾打回轉圈，
                //    而 endTime 還留著——一個「執行中」的列顯示著已完成時長。
                guard !step.status.isTerminal else { return }
                // 2. current 不得倒退。**刻意不看 total**：早先版本允許「total 變了
                //    就接受較小的 current」，那個例外反而是漏洞——亂序到達時它正好
                //    放行會讓計數器彈回的那些事件（5/20 → 90/100 → 6/20），而
                //    fraction 的單調 clamp 會把中間那個虛高值永久釘住，之後真實
                //    推進到 100% 條也不會再動。要重設一個步驟只有一條路：`.started`。
                guard current >= step.current else { return }
                step.status = .running
                step.total = total
                // total > 0 時把 current 夾住。不夾的話 model 與 view 會各自解讀：
                // completion() 這邊 min(1,…) 當它是 100%，SyncPresenter 那邊照印
                // 「90/20」。要夾就在入口夾一次。
                step.current = total > 0 ? min(current, total) : current
                if !detail.isEmpty { step.detail = detail }
            }

        case .finished(let id, let status, let detail):
            assert(status.isTerminal, "`.finished` 只接受終態；\(status) 會讓 finish(.completed) 稍後靜默改寫它")
            mutate(id) { step in
                // 第一個終態說了算，與 `.advanced` 的守衛對稱。
                //
                // 具體會咬人的情況：單字卡 merge 成功、字典卡投影拋非 404。
                // `performPullCardsToLocal` 內部已經發過 `.finished(.pull, .done,
                // "同步 6 筆")`，外層的失敗補救接著又發一次 `.finished(.pull, .error)`
                // —— 卡片明明已經寫進本地庫了，那一列卻從綠翻紅。
                guard !step.status.isTerminal else { return }
                step.status = status
                if !detail.isEmpty { step.detail = detail }
                if step.endTime == nil { step.endTime = Date() }
            }
        }
    }

    /// 收尾。
    ///
    /// `.completed` 下殘留的非終態步驟分兩種，**不能一律打勾**：
    /// - `.running` / `.retry` = 確實跑過了，只是沒發收尾事件 → `.done`。
    /// - `.waiting` = 從頭到尾沒被回報過 → `.skipped`（presenter 畫 `minus.circle.fill`）。
    ///   把它打成綠勾是實打實的謊：宣告了某一步卻整輪沒跑，使用者會看到
    ///   「更新 Podcast 目錄 ✓」而那件事根本沒發生。
    ///
    /// `.failed` 則完全不美化：沒跑到的維持 waiting，進度條也不強制拉滿。
    func finish(_ terminal: SyncPhase) {
        phase = terminal
        if terminal == .completed {
            for index in steps.indices where !steps[index].status.isTerminal {
                steps[index].status = steps[index].status == .waiting ? .skipped : .done
                if steps[index].endTime == nil { steps[index].endTime = Date() }
            }
        }
        recomputeFraction()
        // 整輪完成就是 100%，即使步驟清單是空的（`recomputeFraction` 對空清單
        // 沒有分母可算，會原地留住上一個值 —— 一輪已完成的同步顯示 0% 是壞的）。
        if terminal == .completed { fraction = 1 }
    }

    /// 回到未開始狀態。設定頁在收合動畫結束後呼叫，避免下一次展開閃出上一輪殘影。
    func reset() {
        steps = []
        phase = .ready
        fraction = 0
    }

    // MARK: - Internals

    /// 未宣告的步驟事件直接丟棄——憑空長出一列比少一列更糟（使用者會看到一個
    /// 從未被規劃、也沒人保證會結束的項目）。
    private func mutate(_ id: SyncStepID, _ body: (inout PipelineStep) -> Void) {
        guard let index = steps.firstIndex(where: { $0.id == id.rawValue }) else { return }
        body(&steps[index])
        recomputeFraction()
    }

    private func recomputeFraction() {
        let totalWeight = steps.reduce(0) { $0 + $1.weight }
        guard totalWeight > 0 else { return }
        let earned = steps.reduce(0.0) { $0 + $1.weight * Self.completion(of: $1) }
        // 單調：任何重算都只能往上。步驟重跑（retry）會讓瞬時值下降，
        // 但使用者看到的是「這輪已經走了多遠」，那個量不該倒退。
        fraction = max(fraction, min(1.0, earned / totalWeight))
    }

    private static func completion(of step: PipelineStep) -> Double {
        if step.status.isTerminal { return 1 }
        switch step.status {
        case .waiting:
            return 0
        case .running, .retry:
            guard step.total > 0 else { return runningFloor }
            return max(runningFloor, min(1, Double(step.current) / Double(step.total)))
        case .done, .skipped, .error:
            return 1  // isTerminal 已攔下，這裡只為窮舉
        }
    }
}
