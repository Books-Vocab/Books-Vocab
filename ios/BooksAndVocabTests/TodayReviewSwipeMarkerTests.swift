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

    // MARK: UITest 契約（id + 強度值格式）

    @Test func accessibilityIDsAreStableAndDistinct() {
        #expect(TodayReviewSwipeMarkerKind.remembered.accessibilityID == "todayReview.swipeMarker.remembered")
        #expect(TodayReviewSwipeMarkerKind.forgot.accessibilityID == "todayReview.swipeMarker.forgot")
        #expect(Set(TodayReviewSwipeMarkerKind.allCases.map(\.accessibilityID)).count == 2)
    }

    @Test func accessibilityValueIsFixedTwoDecimalsClampedToUnit() {
        typealias K = TodayReviewSwipeMarkerKind
        #expect(K.accessibilityValue(opacity: 0) == "0.00")
        #expect(K.accessibilityValue(opacity: 0.5) == "0.50")
        #expect(K.accessibilityValue(opacity: 1) == "1.00")
        #expect(K.accessibilityValue(opacity: 1.7) == "1.00")
        #expect(K.accessibilityValue(opacity: -0.2) == "0.00")
    }

    @Test func settledRestPublishesZeroForBothMarkers() {
        // settle no-anim 把 swipeOffset 歸 0 → 兩個標記的發布值同幀為 "0.00"（無殘影）。
        for direction: CGFloat in [-1, 1] {
            let value = TodayReviewSwipeMarkerKind.accessibilityValue(
                opacity: F.markerOpacity(swipeOffset: 0, threshold: threshold, direction: direction)
            )
            #expect(value == "0.00")
        }
    }

    @Test func degenerateThresholdDoesNotDivideByZero() {
        #expect(F.markerOpacity(swipeOffset: 0.5, threshold: 0, direction: 1) == 0.5)
        #expect(F.markerOpacity(swipeOffset: 5, threshold: 0, direction: 1) == 1)
    }

    // MARK: 峰值探針（UITest 正控）

    @Test func peakAccessibilityIDsAreStableAndDistinctFromMarkerIDs() {
        #expect(TodayReviewSwipeMarkerKind.remembered.peakAccessibilityID == "todayReview.swipeMarkerPeak.remembered")
        #expect(TodayReviewSwipeMarkerKind.forgot.peakAccessibilityID == "todayReview.swipeMarkerPeak.forgot")
        let all = TodayReviewSwipeMarkerKind.allCases.flatMap { [$0.accessibilityID, $0.peakAccessibilityID] }
        #expect(Set(all).count == 4)
    }

    @Test func peakTracksMaxAlongDragAndSurvivesRelease() {
        typealias P = TodayReviewSwipeMarkerPeak
        var peak = P.zero
        var previous: CGFloat = 0
        for offset: CGFloat in [20, 60, 40] {
            peak = peak.recording(from: previous, to: offset, threshold: threshold)
            previous = offset
        }
        #expect(peak.remembered == 0.6)
        #expect(peak.forgot == 0)
        // 放開 fling：起點非 0 → 累計取 max，飽和。
        peak = peak.recording(from: previous, to: 393, threshold: threshold)
        #expect(peak.remembered == 1)
        #expect(peak.forgot == 0)
    }

    @Test func peakRestartsWhenAGestureStartsFromRest() {
        typealias P = TodayReviewSwipeMarkerPeak
        let first = P.zero.recording(from: 0, to: 60, threshold: threshold)
        #expect(first.remembered == 0.6)
        // 下一次手勢（offset 由 0 起）清掉上一次的峰值，改記左滑。
        let second = first.recording(from: 0, to: -30, threshold: threshold)
        #expect(second.remembered == 0)
        #expect(second.forgot == 0.3)
    }

    @Test func buttonFlingFromRestSaturatesOnlyTheChosenDirection() {
        for kind in TodayReviewSwipeMarkerKind.allCases {
            let plan = F.plan(
                direction: kind.direction,
                startOffset: 0,
                releaseVelocity: nil,
                screenWidth: 393,
                threshold: threshold,
                baseDuration: 0.18
            )
            let peak = TodayReviewSwipeMarkerPeak.zero.recording(from: 0, to: plan.targetOffset, threshold: threshold)
            #expect(peak.value(for: kind) == 1)
            let other = TodayReviewSwipeMarkerKind.allCases.first { $0 != kind }!
            #expect(peak.value(for: other) == 0)
        }
    }
}
