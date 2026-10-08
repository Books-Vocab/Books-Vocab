import CoreGraphics
import Testing
@testable import BooksAndVocab

/// #2027：swipe 放手與按鈕 / probe fling 共用單一過渡規劃（`TodayReviewFling.plan`）。
/// 不變式：同方向同終點、凍結 intensity = 方向符號、時長只依「牌堆升頂剩多少」連續單調、
/// 升頂已飽和的 swipe 放手維持原 SwipeFling 時長（零回歸），settle 後 toolbar 回饋不硬切。
struct TodayReviewFlingTests {

    private typealias F = TodayReviewFling
    private let width: CGFloat = 393
    private let threshold: CGFloat = 100
    private let base = 0.18

    private func plan(_ direction: CGFloat, start: CGFloat, velocity: CGFloat?) -> F.Plan {
        F.plan(
            direction: direction,
            startOffset: start,
            releaseVelocity: velocity,
            screenWidth: width,
            threshold: threshold,
            baseDuration: base
        )
    }

    // MARK: dismissProgress（拖動與 fling 同源，映射不變）

    @Test func dismissProgressMapsDistanceToRise() {
        #expect(F.dismissProgress(swipeOffset: 0) == 0)
        #expect(F.dismissProgress(swipeOffset: 100) == 0.5)
        #expect(F.dismissProgress(swipeOffset: -100) == 0.5)
        #expect(F.dismissProgress(swipeOffset: 200) == 1)
        #expect(F.dismissProgress(swipeOffset: -900) == 1)
    }

    // MARK: plan — 單一路徑

    @Test func buttonAndSwipeShareTargetAndFeedback() {
        for direction: CGFloat in [-1, 1] {
            let button = plan(direction, start: 0, velocity: nil)
            let swipe = plan(direction, start: direction * 150, velocity: F.nominalReleaseVelocity)
            #expect(button.targetOffset == swipe.targetOffset)
            #expect(button.frozenIntensity == swipe.frozenIntensity)
        }
    }

    @Test func frozenIntensityIsDirectionSignFromTheFirstFrame() {
        // 按鈕按下（offset 0）即有完整回饋，不再凍結成 0。
        for start: CGFloat in [-240, -100, -20, 0, 20, 100, 240] {
            #expect(plan(1, start: start, velocity: nil).frozenIntensity == 1)
            #expect(plan(-1, start: start, velocity: nil).frozenIntensity == -1)
        }
    }

    @Test func targetDistanceKeepsVelocityBonus() {
        let slow = plan(1, start: 150, velocity: 0)
        let fast = plan(1, start: 150, velocity: 5000)
        #expect(slow.targetOffset == width * 1.3)
        #expect(fast.targetOffset == width * 1.3 + 0.5 * width * 0.4)
        #expect(plan(-1, start: -150, velocity: 5000).targetOffset == -fast.targetOffset)
    }

    // MARK: plan — 時長

    @Test func saturatedSwipeReleaseKeepsBaseDuration() {
        // 升頂已完成（|offset| ≥ 200）的 swipe 放手 = 原 SwipeFling spring，零回歸。
        for start: CGFloat in [200, 260, 400] {
            #expect(plan(1, start: start, velocity: 1500).duration == base)
            #expect(plan(-1, start: -start, velocity: 1500).duration == base)
        }
    }

    @Test func buttonFlingIsNotHastierThanSwipeRelease() {
        let button = plan(1, start: 0, velocity: nil).duration
        let atThreshold = plan(1, start: threshold, velocity: 1200).duration
        #expect(button > atThreshold)
        #expect(atThreshold > base)
        #expect(button <= base * (1 + F.remainingRiseDurationScale) + 1e-9)
    }

    @Test func durationIsContinuousAndMonotoneInProgressAlongDirection() {
        var last = Double.infinity
        var start: CGFloat = 0
        while start <= 260 {
            let d = plan(1, start: start, velocity: nil).duration
            #expect(d <= last + 1e-12)
            if last.isFinite { #expect(last - d < 0.01) }
            last = d
            start += 2
        }
    }

    @Test func oppositeSideStartCountsAsFullRise() {
        // 拖右 80pt 時按「忘記」：往左飛，牌堆升頂從 0 起算，時長 = 按鈕時長。
        #expect(plan(-1, start: 80, velocity: nil).duration == plan(-1, start: 0, velocity: nil).duration)
    }

    @Test func longestFlingFitsInsideSafetyNet() {
        // 800ms safety net 不得在正常 spring 完成前觸發。
        #expect(plan(1, start: 0, velocity: nil).duration < 0.4)
    }

    // MARK: toolbarIntensity

    @Test func toolbarHoldsFrozenFeedbackDuringFling() {
        #expect(F.toolbarIntensity(animatingOut: true, frozen: -1, swipeEnabled: false, swipeOffset: 0, threshold: threshold) == -1)
    }

    @Test func toolbarRelaxesFromFrozenAfterSettleInsteadOfSnapping() {
        // settle 的 no-anim transaction 只放下 dismissPhase；凍結值在下一個 runloop
        // 以動畫歸零 —— 中間這一幀 toolbar 仍讀凍結值，不被 no-anim 硬切回 0。
        #expect(F.toolbarIntensity(animatingOut: false, frozen: 1, swipeEnabled: true, swipeOffset: 0, threshold: threshold) == 1)
        #expect(F.toolbarIntensity(animatingOut: false, frozen: 0, swipeEnabled: true, swipeOffset: 0, threshold: threshold) == 0)
    }

    @Test func toolbarTracksDragWhenIdle() {
        #expect(F.toolbarIntensity(animatingOut: false, frozen: 0, swipeEnabled: true, swipeOffset: 50, threshold: threshold) == 0.5)
        #expect(F.toolbarIntensity(animatingOut: false, frozen: 0, swipeEnabled: true, swipeOffset: -300, threshold: threshold) == -1)
        #expect(F.toolbarIntensity(animatingOut: false, frozen: 0, swipeEnabled: false, swipeOffset: 80, threshold: threshold) == 0)
    }
}
