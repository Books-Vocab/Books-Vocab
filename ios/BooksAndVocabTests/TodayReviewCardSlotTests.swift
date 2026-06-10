import CoreGraphics
import Testing
@testable import BooksAndVocab

/// Phase 3a 常駐雙 slot 輪替的純邏輯契約。
///
/// `TodayReviewCardSlotLayout` 是 settle hitch 修復的核心不變量來源：
/// 兩個固定 identity 的 slot（slot = index % 2）永久存活，promote 時只翻
/// role，**incoming slot 的內容 index 不變** —— 這個「零內容 diff」前提
/// 必須在純函數層被窮舉證明，不依賴 View 建構。
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

    /// 對 queueCount 1...6 × currentIndex 0..<count 窮舉：
    /// - active slot 恆為 currentIndex % 2，內容 = currentIndex
    /// - 另一 slot：有下一張 → (.preview, currentIndex+1)；隊尾 → (.hidden, clamp 到 currentIndex)
    @Test func roleMatrixIsExhaustivelyCorrect() {
        for queueCount in 1...6 {
            for currentIndex in 0..<queueCount {
                let slots = assignments(currentIndex: currentIndex, queueCount: queueCount)
                let activeSlot = currentIndex % 2
                let otherSlot = 1 - activeSlot

                #expect(TodayReviewCardSlotLayout.activeSlot(currentIndex: currentIndex) == activeSlot)
                #expect(slots[activeSlot] == TodayReviewCardSlotAssignment(role: .active, cardIndex: currentIndex),
                        "active slot mismatch at index \(currentIndex)/\(queueCount)")

                if currentIndex + 1 < queueCount {
                    #expect(slots[otherSlot] == TodayReviewCardSlotAssignment(role: .preview, cardIndex: currentIndex + 1),
                            "preview slot mismatch at index \(currentIndex)/\(queueCount)")
                } else {
                    // 隊尾：preview 不存在 → hidden 且內容 clamp 到 active 卡，
                    // 讓「進入/離開隊尾」永遠是 value diff、不是結構 diff。
                    #expect(slots[otherSlot] == TodayReviewCardSlotAssignment(role: .hidden, cardIndex: currentIndex),
                            "tail slot mismatch at index \(currentIndex)/\(queueCount)")
                }
            }
        }
    }

    /// Completion（currentIndex == queueCount）：兩 slot 皆 hidden，內容 clamp 至末卡。
    @Test func completionHidesBothSlots() {
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
    /// 「將成為 active 的 slot」在推進前後的 cardIndex 完全相同（i+1）。
    @Test func submitAdvanceKeepsIncomingSlotContentStable() {
        let queueCount = 6
        var session = TodayReviewSessionState(queue: Array(0..<queueCount))

        while session.currentIndex < queueCount - 1 {
            let before = session.currentIndex
            let incomingSlot = TodayReviewCardSlotLayout.activeSlot(currentIndex: before + 1)
            let beforeAssignment = TodayReviewCardSlotLayout.assignment(
                slot: incomingSlot, currentIndex: before, queueCount: queueCount)

            session.advanceAfterSubmission()

            let afterAssignment = TodayReviewCardSlotLayout.assignment(
                slot: incomingSlot, currentIndex: session.currentIndex, queueCount: queueCount)

            #expect(beforeAssignment.role == .preview)
            #expect(afterAssignment.role == .active)
            #expect(beforeAssignment.cardIndex == afterAssignment.cardIndex,
                    "promote at \(before)→\(before + 1) 改變了 incoming slot 內容")
        }
    }

    /// goPrevious i→i-1：原 active slot 變 preview 且內容 index 不變（仍是卡 i），
    /// 新 active slot 換內容（卡 i-1）—— 退場側才付 content diff。
    @Test func previousFlipsRolesAndKeepsOutgoingContentStable() {
        let queueCount = 5
        var session = TodayReviewSessionState(queue: Array(0..<queueCount), currentIndex: queueCount - 1)

        while session.canGoPrevious {
            let before = session.currentIndex
            let outgoingSlot = TodayReviewCardSlotLayout.activeSlot(currentIndex: before)
            session.goPrevious()
            let after = session.currentIndex
            #expect(after == before - 1)

            let outgoing = TodayReviewCardSlotLayout.assignment(
                slot: outgoingSlot, currentIndex: after, queueCount: queueCount)
            let incoming = TodayReviewCardSlotLayout.assignment(
                slot: 1 - outgoingSlot, currentIndex: after, queueCount: queueCount)

            #expect(outgoing == TodayReviewCardSlotAssignment(role: .preview, cardIndex: before))
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

    /// 最後一張卡 submit → completion：active slot 翻 hidden（presenter 隨後切 completionState）。
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

    // MARK: - Transform（promote 零視覺 diff 前提）

    private func approx(_ a: Double, _ b: Double, tolerance: Double = 1e-9) -> Bool {
        abs(a - b) < tolerance
    }

    private func approx(_ a: CGFloat, _ b: CGFloat, tolerance: CGFloat = 1e-9) -> Bool {
        abs(a - b) < tolerance
    }

    /// settle 翻 role 的瞬間：preview@progress=1 的 transform 必須與
    /// active@swipeOffset=0 完全一致 —— 這就是「promote = 純 hit-testing
    /// gate 翻面、零視覺 diff」的數學前提。
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

    /// hidden slot：透明度恆 0，但幾何與 preview 同源（避免重新出場時跳位）。
    @Test func hiddenSlotIsInvisibleWithPreviewGeometry() {
        for progress in [CGFloat(0), 0.4, 1] {
            let hidden = TodayReviewCardSlotLayout.transform(
                role: .hidden, swipeOffset: 0, dismissProgress: progress,
                stackRotation: 0.2, screenWidth: 393, introProgress: 1)
            let preview = TodayReviewCardSlotLayout.transform(
                role: .preview, swipeOffset: 0, dismissProgress: progress,
                stackRotation: 0.2, screenWidth: 393, introProgress: 1)

            #expect(hidden.opacity == 0)
            #expect(approx(hidden.scale, preview.scale))
            #expect(approx(hidden.yOffset, preview.yOffset))
            #expect(approx(hidden.rotationDegrees, preview.rotationDegrees))
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
    /// introProgress 1 → identity。
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

        // intro 只屬於 active；preview/hidden 不受 introProgress 影響。
        let preview = TodayReviewCardSlotLayout.transform(
            role: .preview, swipeOffset: 0, dismissProgress: 0,
            stackRotation: 0, screenWidth: 393, introProgress: 0)
        #expect(approx(preview.scale, 1.0 - 0.025))
    }
}
