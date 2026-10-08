import CoreGraphics
import Testing
@testable import BooksAndVocab

/// #2045：卡片方向標記（右滑「記得」、左滑「忘記」）的不透明度純函數。
/// 不變式：0 位移為 0、閾值飽和為 1、連續、沿方向單調、反方向恆 0、兩標記互斥。
struct TodayReviewSwipeMarkerTests {

    private typealias F = TodayReviewFling
    private let threshold: CGFloat = 100

    private func remember(_ offset: CGFloat) -> Double {
        F.markerOpacity(swipeOffset: offset, threshold: threshold, direction: 1)
    }

    private func forget(_ offset: CGFloat) -> Double {
        F.markerOpacity(swipeOffset: offset, threshold: threshold, direction: -1)
    }

    @Test func restIsInvisible() {
        #expect(remember(0) == 0)
        #expect(forget(0) == 0)
    }

    @Test func saturatesAtThresholdAndBeyond() {
        for offset: CGFloat in [100, 150, 600] {
            #expect(remember(offset) == 1)
            #expect(forget(-offset) == 1)
        }
    }

    @Test func tracksDragProgressBelowThreshold() {
        #expect(remember(25) == 0.25)
        #expect(remember(50) == 0.5)
        #expect(forget(-75) == 0.75)
    }

    @Test func oppositeDirectionStaysHidden() {
        for offset: CGFloat in [1, 50, 100, 600] {
            #expect(remember(-offset) == 0)
            #expect(forget(offset) == 0)
        }
    }

    @Test func continuousAndMonotoneAlongDirection() {
        var last = 0.0
        var offset: CGFloat = 0
        while offset <= 160 {
            let r = remember(offset)
            #expect(r >= last)
            #expect(r - last <= 0.0101)
            #expect(forget(-offset) == r)
            last = r
            offset += 1
        }
    }

    @Test func atMostOneMarkerVisible() {
        var offset: CGFloat = -300
        while offset <= 300 {
            #expect(min(remember(offset), forget(offset)) == 0)
            offset += 5
        }
    }

    @Test func flingTargetShowsFullMarkerForBothSources() {
        // swipe 放手與按鈕走同一 plan：終點 offset 處標記滿值，動畫期間沿同一 spring 漸入。
        for direction: CGFloat in [-1, 1] {
            for start: CGFloat in [0, direction * 150] {
                let plan = F.plan(
                    direction: direction,
                    startOffset: start,
                    releaseVelocity: start == 0 ? nil : 1200,
                    screenWidth: 393,
                    threshold: threshold,
                    baseDuration: 0.18
                )
                #expect(F.markerOpacity(swipeOffset: plan.targetOffset, threshold: threshold, direction: direction) == 1)
            }
        }
    }

    @Test func degenerateThresholdDoesNotDivideByZero() {
        #expect(F.markerOpacity(swipeOffset: 0.5, threshold: 0, direction: 1) == 0.5)
        #expect(F.markerOpacity(swipeOffset: 5, threshold: 0, direction: 1) == 1)
    }
}
