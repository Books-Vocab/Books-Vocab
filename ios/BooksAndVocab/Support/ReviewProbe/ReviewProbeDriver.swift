import Foundation
import SwiftUI

/// Probe 迴圈對 review session 的最小視角 — 抽象成 protocol 讓 driver
/// 可以用 mock session 做單元測試（`TodayReviewState` 的完整初始化牽動
/// UserDefaults / snapshot restore，不適合進測試）。
@MainActor
protocol ReviewProbeSessionDriving: AnyObject {
    var probeHasCurrentCard: Bool { get }
    var probeIsShowingFront: Bool { get }
    func probeRevealCurrentCard()
}

extension TodayReviewState: ReviewProbeSessionDriving {
    var probeHasCurrentCard: Bool { currentEntry != nil }
    var probeIsShowingFront: Bool { revealStage == .front }
    /// 鏡像 `performReviewIntent(.reveal)` 的動畫包法（同 spring）—— 不直呼
    /// 該方法是因為它需要 container/reviewSettings，probe 的 reveal 不該觸碰。
    func probeRevealCurrentCard() {
        withAnimation(AppMotion.reviewRevealSpring) { advanceReveal() }
    }
}

/// 驅動「reveal → 評分 fling」迴圈的協調者。
///
/// 分工：迴圈讀 reference 型 `TodayReviewState`（永遠新鮮），但 fling 必須走
/// presenter 層的 `flingCard()`（suppress / settle 的全套機械都在那裡，也是
/// 評分按鈕的同一個 entry point）。presenter 是 value 型 view，所以由它在
/// `.task` 註冊 `flingHandler` 閉包 — 閉包內只碰 @State（讀 live storage，
/// 無 stale-struct 問題）。
///
/// marker 走 NSLog（Release 也可見，`devicectl --console` / simctl 可收）。
@MainActor
final class ReviewProbeDriver {
    let plan: ReviewProbePlan

    /// presenter 註冊的 fling 入口。回傳 false = 當下不能 fling
    /// （dismissPhase 非 idle），driver 會等 interFlip 後重試。
    var flingHandler: ((_ direction: CGFloat, _ remember: Bool) -> Bool)?

    /// 逐 flip 幀取樣 + JSONL 落檔（ReviewProbeMetrics）。nil = 只發 marker。
    var metrics: ReviewProbeMetricsRecording?

    /// 測試注入點：marker 輸出與 sleep。
    var emit: (String) -> Void = { NSLog("%@", $0) }
    var sleep: (Duration) async -> Void = { try? await Task.sleep(for: $0) }

    private(set) var flipsCompleted = 0
    private(set) var finished = false

    init(plan: ReviewProbePlan) {
        self.plan = plan
    }

    /// 跑完整個量測迴圈。idempotent：view re-appear 重觸發 `.task` 時，
    /// 已完成的 run 不會重啟。
    func run(session: ReviewProbeSessionDriving) async {
        guard !finished else { return }
        emit("KG_REVIEW_PROBE start flips=\(plan.flipCount)")
        metrics?.startRun()
        await sleep(plan.warmup)

        var consecutiveFailures = 0
        while flipsCompleted < plan.flipCount, !Task.isCancelled {
            guard session.probeHasCurrentCard else { break }

            if session.probeIsShowingFront {
                session.probeRevealCurrentCard()
                await sleep(plan.revealHold)
                if Task.isCancelled { break }
            }

            let remember = plan.remember(at: flipsCompleted)
            // recorder 在 fling 前開 — 視窗涵蓋 fling 起點，對齊 settle.frames。
            metrics?.beginFlip(index: flipsCompleted, remember: remember)
            if let handler = flingHandler, handler(remember ? 1 : -1, remember) {
                flipsCompleted += 1
                consecutiveFailures = 0
                emit("KG_REVIEW_PROBE flip i=\(flipsCompleted) fb=\(remember ? "R" : "F")")
                await sleep(plan.settleWindow)
                metrics?.endFlip()
                await sleep(plan.interFlipRemainder)
            } else {
                metrics?.cancelFlip()
                consecutiveFailures += 1
                if consecutiveFailures >= plan.maxConsecutiveFailures {
                    emit("KG_REVIEW_PROBE abort reason=fling_unavailable failures=\(consecutiveFailures)")
                    finished = true
                    metrics?.finishRun(aborted: true)
                    return
                }
                await sleep(plan.interFlip)
            }
        }

        finished = true
        if Task.isCancelled {
            // view teardown / identity 變更取消了 .task —— 不可與正常結束
            // 同 marker，外部 collector 才不會把殘缺 run 當成功。
            metrics?.finishRun(aborted: true)
            emit("KG_REVIEW_PROBE abort reason=cancelled flips=\(flipsCompleted)")
        } else {
            metrics?.finishRun(aborted: false)
            emit("KG_REVIEW_PROBE done flips=\(flipsCompleted)")
        }
    }
}

// MARK: - Environment plumbing

/// 經 Environment 下發，避免動 `TodayReviewView` / `TodayReviewPresenter`
/// 的 init 簽名（兩個生產呼叫點 + preview）。一般啟動 default nil，
/// 兩端的 `.task` 直接 guard return — 對 hot path 零行為改動。
private struct ReviewProbeDriverKey: EnvironmentKey {
    static let defaultValue: ReviewProbeDriver? = nil
}

extension EnvironmentValues {
    var reviewProbeDriver: ReviewProbeDriver? {
        get { self[ReviewProbeDriverKey.self] }
        set { self[ReviewProbeDriverKey.self] = newValue }
    }
}
