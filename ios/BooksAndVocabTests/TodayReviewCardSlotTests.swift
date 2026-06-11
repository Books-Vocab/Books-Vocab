import CoreGraphics
import Testing
@testable import BooksAndVocab

/// Phase 4 三常駐 slot 輪替的純邏輯契約。
///
/// `TodayReviewCardSlotLayout` 是 settle「深度堆疊 pop」修復的核心不變量來源：
/// 三個固定 identity 的 slot（slot = index % 3）永久存活，fling 期間
/// preview 升頂、underPreview 升至 depth-1；settle 只翻 role —— 兩個存活
/// slot 的內容 index 不變（零內容 diff），唯一的內容 diff 落在被回收、
/// 沉到最深層 depth-2 的 slot。這些前提必須在純函數層被窮舉證明。
struct TodayReviewCardSlotTests {

    private func assignments(currentIndex: Int, queueCount: Int) -> [TodayReviewCardSlotAssignment] {
        (0..<TodayReviewCardSlotLayout.slotCount).map { slot in
            TodayReviewCardSlotLayout.assignment(
                slot: slot,
                currentIndex: currentIndex,
                queueCount: queueCount
            )
        }
    }

    // MARK: - Role matrix（窮舉）

    /// 對 queueCount 1...7 × currentIndex 0..<count 窮舉：
    /// - active slot 恆為 currentIndex % 3，內容 = currentIndex
    /// - preview 後繼 slot（(currentIndex+1) % 3）：有下一張 → (.preview, i+1)；
    ///   越界 → (.hidden, clamp)
    /// - underPreview 後繼 slot（(currentIndex+2) % 3）：有第三張 → (.underPreview, i+2)；
    ///   越界 → (.hidden, clamp)
    /// hidden 的 clamp = min(target, count-1)，使「進入/離開隊尾」恆為值 diff
    /// 且 demote 路徑（underPreview → preview 後繼）內容不變。
    @Test func roleMatrixIsExhaustivelyCorrect() {
        for queueCount in 1...7 {
            for currentIndex in 0..<queueCount {
                let slots = assignments(currentIndex: currentIndex, queueCount: queueCount)
                let activeSlot = currentIndex % 3
                let previewSlot = (currentIndex + 1) % 3
                let underSlot = (currentIndex + 2) % 3

                #expect(TodayReviewCardSlotLayout.activeSlot(currentIndex: currentIndex) == activeSlot)
                #expect(slots[activeSlot] == TodayReviewCardSlotAssignment(role: .active, cardIndex: currentIndex),
                        "active slot mismatch at index \(currentIndex)/\(queueCount)")

                if currentIndex + 1 < queueCount {
                    #expect(slots[previewSlot] == TodayReviewCardSlotAssignment(role: .preview, cardIndex: currentIndex + 1),
                            "preview slot mismatch at index \(currentIndex)/\(queueCount)")
                } else {
                    #expect(slots[previewSlot] == TodayReviewCardSlotAssignment(role: .hidden, cardIndex: queueCount - 1),
                            "preview-successor tail mismatch at index \(currentIndex)/\(queueCount)")
                }

                if currentIndex + 2 < queueCount {
                    #expect(slots[underSlot] == TodayReviewCardSlotAssignment(role: .underPreview, cardIndex: currentIndex + 2),
                            "underPreview slot mismatch at index \(currentIndex)/\(queueCount)")
                } else {
                    #expect(slots[underSlot] == TodayReviewCardSlotAssignment(
                        role: .hidden, cardIndex: min(currentIndex + 2, queueCount - 1)),
                            "under-successor tail mismatch at index \(currentIndex)/\(queueCount)")
                }
            }
        }
    }

    /// Completion（currentIndex == queueCount）：三 slot 皆 hidden，內容 clamp 至末卡。
    @Test func completionHidesAllSlots() {
        for queueCount in 1...4 {
            let slots = assignments(currentIndex: queueCount, queueCount: queueCount)
            for slot in slots {
                #expect(slot.role == .hidden)
                #expect(slot.cardIndex == queueCount - 1)
            }
        }
    }

    /// 空 queue / 退化輸入：total function，不 crash、全 hidden。
    @Test func emptyQueueIsTotallyHidden() {
        let slots = assignments(currentIndex: 0, queueCount: 0)
        for slot in slots {
            #expect(slot.role == .hidden)
            #expect(slot.cardIndex == 0)
        }
    }

    // MARK: - Navigation invariants（用真 session state 驅動 index 流轉）

    /// Promote 零內容 diff 核心不變量：submit 推進 i→i+1 時，
    /// 兩個存活 slot 的 cardIndex 完全不變：
    /// - preview 後繼 slot：preview(i+1) → active(i+1)
    /// - under 後繼 slot：underPreview(i+2) → preview(i+2)（隊尾 hidden 亦值穩定）
    /// 唯一內容 diff 落在被回收的舊 active slot（→ 最深層 underPreview/hidden）。
    @Test func submitAdvanceKeepsSurvivingSlotContentStable() {
        let queueCount = 8
        var session = TodayReviewSessionState(queue: Array(0..<queueCount))

        while session.currentIndex < queueCount - 1 {
            let before = session.currentIndex
            let incomingSlot = TodayReviewCardSlotLayout.activeSlot(currentIndex: before + 1)
            let demotingSlot = TodayReviewCardSlotLayout.activeSlot(currentIndex: before + 2)
            let recycledSlot = TodayReviewCardSlotLayout.activeSlot(currentIndex: before)

            let incomingBefore = TodayReviewCardSlotLayout.assignment(
                slot: incomingSlot, currentIndex: before, queueCount: queueCount)
            let demotingBefore = TodayReviewCardSlotLayout.assignment(
                slot: demotingSlot, currentIndex: before, queueCount: queueCount)

            session.advanceAfterSubmission()
            let after = session.currentIndex

            let incomingAfter = TodayReviewCardSlotLayout.assignment(
                slot: incomingSlot, currentIndex: after, queueCount: queueCount)
            let demotingAfter = TodayReviewCardSlotLayout.assignment(
                slot: demotingSlot, currentIndex: after, queueCount: queueCount)
            let recycledAfter = TodayReviewCardSlotLayout.assignment(
                slot: recycledSlot, currentIndex: after, queueCount: queueCount)

            #expect(incomingBefore.role == .preview)
            #expect(incomingAfter.role == .active)
            #expect(incomingBefore.cardIndex == incomingAfter.cardIndex,
                    "promote at \(before)→\(after) 改變了 incoming slot 內容")

            #expect(demotingBefore.cardIndex == demotingAfter.cardIndex,
                    "demote at \(before)→\(after) 改變了 under slot 內容")
            if before + 2 < queueCount {
                #expect(demotingBefore.role == .underPreview)
                #expect(demotingAfter.role == .preview)
            }

            // 內容 diff 只允許出現在回收 slot（沉到最深層）。
            if after + 2 < queueCount {
                #expect(recycledAfter == TodayReviewCardSlotAssignment(role: .underPreview, cardIndex: after + 2))
            } else {
                #expect(recycledAfter.role == .hidden)
            }
        }
    }

    /// goPrevious i→i-1：原 active slot 變 preview（內容仍是卡 i，零 diff）、
    /// 原 preview slot 變 underPreview（內容仍是 i+1，零 diff）—— content diff
    /// 只落在升為 active 的原 under 後繼 slot。
    @Test func previousRotatesRolesAndKeepsDemotedContentStable() {
        let queueCount = 7
        var session = TodayReviewSessionState(queue: Array(0..<queueCount), currentIndex: queueCount - 3)

        while session.canGoPrevious {
            let before = session.currentIndex
            let outgoingSlot = TodayReviewCardSlotLayout.activeSlot(currentIndex: before)
            let previewSlot = TodayReviewCardSlotLayout.activeSlot(currentIndex: before + 1)
            session.goPrevious()
            let after = session.currentIndex
            #expect(after == before - 1)

            let outgoing = TodayReviewCardSlotLayout.assignment(
                slot: outgoingSlot, currentIndex: after, queueCount: queueCount)
            let demotedPreview = TodayReviewCardSlotLayout.assignment(
                slot: previewSlot, currentIndex: after, queueCount: queueCount)
            let incoming = TodayReviewCardSlotLayout.assignment(
                slot: TodayReviewCardSlotLayout.activeSlot(currentIndex: after),
                currentIndex: after, queueCount: queueCount)

            #expect(outgoing == TodayReviewCardSlotAssignment(role: .preview, cardIndex: before))
            if before + 1 < queueCount {
                #expect(demotedPreview == TodayReviewCardSlotAssignment(role: .underPreview, cardIndex: before + 1))
            } else {
                #expect(demotedPreview.role == .hidden)
            }
            #expect(incoming == TodayReviewCardSlotAssignment(role: .active, cardIndex: after))
        }
    }

    /// shuffle 不動 currentIndex → slot 指派（純 f(currentIndex, queueCount)）不變。
    @Test func shuffleKeepsAssignmentsStable() {
        let queueCount = 8
        var session = TodayReviewSessionState(queue: Array(0..<queueCount), currentIndex: 3)
        let before = assignments(currentIndex: session.currentIndex, queueCount: queueCount)

        var rng = SystemRandomNumberGenerator()
        let didShuffle = session.shuffleRemaining(using: &rng)
        #expect(didShuffle)

        let after = assignments(currentIndex: session.currentIndex, queueCount: queueCount)
        #expect(before == after)
    }

    /// 最後一張卡 submit → completion：全 slot 翻 hidden（presenter 隨後切 completionState）。
    @Test func finalSubmitReachesCompletionAssignments() {
        let queueCount = 3
        var session = TodayReviewSessionState(queue: Array(0..<queueCount), currentIndex: queueCount - 1)
        let reachedCompletion = session.advanceAfterSubmission()
        #expect(reachedCompletion)
        #expect(session.isComplete)

        let slots = assignments(currentIndex: session.currentIndex, queueCount: queueCount)
        for slot in slots {
            #expect(slot.role == .hidden)
            #expect(slot.cardIndex == queueCount - 1)
        }
    }

    // MARK: - Transform（settle 零視覺 diff 前提）

    private func approx(_ a: Double, _ b: Double, tolerance: Double = 1e-9) -> Bool {
        abs(a - b) < tolerance
    }

    private func approx(_ a: CGFloat, _ b: CGFloat, tolerance: CGFloat = 1e-9) -> Bool {
        abs(a - b) < tolerance
    }

    /// settle 翻 role 的瞬間：preview@progress=1 的 transform 必須與
    /// active@swipeOffset=0 完全一致 —— promote 零視覺 diff 的數學前提。
    @Test func promoteTransformIsZeroDiff() {
        let landed = TodayReviewCardSlotLayout.transform(
            role: .preview, swipeOffset: 0, dismissProgress: 1,
            stackRotation: 0.83, screenWidth: 393, introProgress: 1)
        let active = TodayReviewCardSlotLayout.transform(
            role: .active, swipeOffset: 0, dismissProgress: 0,
            stackRotation: 0.83, screenWidth: 393, introProgress: 1)

        #expect(approx(landed.scale, active.scale))
        #expect(approx(landed.xOffset, active.xOffset))
        #expect(approx(landed.yOffset, active.yOffset))
        #expect(approx(landed.rotationDegrees, active.rotationDegrees))
        #expect(approx(landed.opacity, active.opacity))
        #expect(approx(landed.opacity, 1.0))

        // 邊框透明度同樣收斂到 active 值（消滅舊雙軌 0.45→0.72 的 settle pop）。
        #expect(approx(
            TodayReviewCardSlotLayout.borderOpacity(role: .preview, dismissProgress: 1),
            TodayReviewCardSlotLayout.borderOpacity(role: .active, dismissProgress: 0)))
    }

    /// 連續堆疊第二道邊界：underPreview@progress=1 必須與 preview@progress=0
    /// 完全一致 —— settle 時 under slot 翻成 preview 零視覺 diff 的數學前提。
    @Test func underPreviewPromotionIsZeroDiff() {
        let risen = TodayReviewCardSlotLayout.transform(
            role: .underPreview, swipeOffset: 0, dismissProgress: 1,
            stackRotation: -0.4, screenWidth: 393, introProgress: 1)
        let idlePreview = TodayReviewCardSlotLayout.transform(
            role: .preview, swipeOffset: 0, dismissProgress: 0,
            stackRotation: -0.4, screenWidth: 393, introProgress: 1)

        #expect(approx(risen.scale, idlePreview.scale))
        #expect(approx(risen.xOffset, idlePreview.xOffset))
        #expect(approx(risen.yOffset, idlePreview.yOffset))
        #expect(approx(risen.rotationDegrees, idlePreview.rotationDegrees))
        #expect(approx(risen.opacity, idlePreview.opacity))

        #expect(approx(
            TodayReviewCardSlotLayout.borderOpacity(role: .underPreview, dismissProgress: 1),
            TodayReviewCardSlotLayout.borderOpacity(role: .preview, dismissProgress: 0)))
    }

    /// idle 底卡（progress=0）必須等於舊 stackCard depth-1 的常數：
    /// scale 0.975、yOff 5、rotation = stackRotation、layer opacity 0.72、border 0.45。
    @Test func idlePreviewMatchesLegacyDeckPose() {
        let t = TodayReviewCardSlotLayout.transform(
            role: .preview, swipeOffset: 0, dismissProgress: 0,
            stackRotation: -0.6, screenWidth: 393, introProgress: 1)

        #expect(approx(t.scale, 1.0 - 0.025))
        #expect(approx(t.xOffset, 0))
        #expect(approx(t.yOffset, 5))
        #expect(approx(t.rotationDegrees, -0.6))
        #expect(approx(t.opacity, TodayReviewMetrics.cardBorderActiveOpacity))
        #expect(approx(
            TodayReviewCardSlotLayout.borderOpacity(role: .preview, dismissProgress: 0),
            TodayReviewMetrics.cardBorderOpacity))
    }

    /// idle 最深卡（depth-2）：同一條線性 depth 公式外推 —— scale 0.95、yOff 10、
    /// rotation 不衰減（深層恆全量 stackRotation）、layer/border opacity 沿線外推。
    @Test func idleUnderPreviewExtendsDepthFormulas() {
        let base = TodayReviewMetrics.cardBorderActiveOpacity
        let t = TodayReviewCardSlotLayout.transform(
            role: .underPreview, swipeOffset: 0, dismissProgress: 0,
            stackRotation: 0.7, screenWidth: 393, introProgress: 1)

        #expect(approx(t.scale, 1.0 - 2 * 0.025))
        #expect(approx(t.xOffset, 0))
        #expect(approx(t.yOffset, 10))
        #expect(approx(t.rotationDegrees, 0.7))
        #expect(approx(t.opacity, max(0, 1.0 - (1.0 - base) * 2)))
        #expect(approx(
            TodayReviewCardSlotLayout.borderOpacity(role: .underPreview, dismissProgress: 0),
            max(0, TodayReviewMetrics.cardBorderActiveOpacity
                - (TodayReviewMetrics.cardBorderActiveOpacity - TodayReviewMetrics.cardBorderOpacity) * 2)))
    }

    /// underPreview 的 rotation 在整段 fling（depth 2→1）不衰減：
    /// 衰減只屬於 preview→active 的最後一段（depth < 1）。
    @Test func underPreviewRotationStaysConstantDuringRise() {
        for progress in [CGFloat(0), 0.3, 0.7, 1] {
            let t = TodayReviewCardSlotLayout.transform(
                role: .underPreview, swipeOffset: 0, dismissProgress: progress,
                stackRotation: 0.9, screenWidth: 393, introProgress: 1)
            #expect(approx(t.rotationDegrees, 0.9), "rotation 在 progress=\(progress) 不應衰減")
        }
    }

    /// hidden slot：透明度恆 0，幾何與 underPreview 同源 —— 三 slot 制下
    /// 重新出場永遠從最深層浮現，值 diff 不跳位。
    @Test func hiddenSlotIsInvisibleWithUnderPreviewGeometry() {
        for progress in [CGFloat(0), 0.4, 1] {
            let hidden = TodayReviewCardSlotLayout.transform(
                role: .hidden, swipeOffset: 0, dismissProgress: progress,
                stackRotation: 0.2, screenWidth: 393, introProgress: 1)
            let under = TodayReviewCardSlotLayout.transform(
                role: .underPreview, swipeOffset: 0, dismissProgress: progress,
                stackRotation: 0.2, screenWidth: 393, introProgress: 1)

            #expect(hidden.opacity == 0)
            #expect(approx(hidden.scale, under.scale))
            #expect(approx(hidden.yOffset, under.yOffset))
            #expect(approx(hidden.rotationDegrees, under.rotationDegrees))
        }
    }

    /// active 追手指：xOffset == swipeOffset，rotation / opacity 套舊互動卡公式。
    @Test func activeTransformTracksSwipeFormulas() {
        let width: CGFloat = 393
        for offset in [CGFloat(-220), -60, 0, 90, 300] {
            let t = TodayReviewCardSlotLayout.transform(
                role: .active, swipeOffset: offset, dismissProgress: min(abs(offset) / 200, 1),
                stackRotation: 0.5, screenWidth: width, introProgress: 1)

            #expect(approx(t.xOffset, offset))
            #expect(approx(t.rotationDegrees, Double(offset) / Double(width) * TodayReviewMetrics.swipeMaxRotation))
            #expect(approx(
                t.opacity,
                1.0 - Double(abs(offset)) / Double(width) * (1.0 - TodayReviewMetrics.swipeOpacityFloor)))
        }
    }

    /// 首插入動畫（取代 .reviewCardPromote insertion）：introProgress 0 → promote 起始姿態，
    /// introProgress 1 → identity。intro 只屬於 active；preview/hidden 不受影響。
    @Test func introTransformReplacesPromoteTransition() {
        let start = TodayReviewCardSlotLayout.transform(
            role: .active, swipeOffset: 0, dismissProgress: 0,
            stackRotation: 0, screenWidth: 393, introProgress: 0)
        #expect(approx(start.scale, TodayReviewMetrics.promoteScale))
        #expect(approx(start.yOffset, TodayReviewMetrics.promoteYOffset))

        let settled = TodayReviewCardSlotLayout.transform(
            role: .active, swipeOffset: 0, dismissProgress: 0,
            stackRotation: 0, screenWidth: 393, introProgress: 1)
        #expect(approx(settled.scale, 1.0))
        #expect(approx(settled.yOffset, 0))

        let preview = TodayReviewCardSlotLayout.transform(
            role: .preview, swipeOffset: 0, dismissProgress: 0,
            stackRotation: 0, screenWidth: 393, introProgress: 0)
        #expect(approx(preview.scale, 1.0 - 0.025))
    }
}
