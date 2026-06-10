import SwiftUI

// MARK: - Resident Card Slots (Phase 3a)
//
// Settle hitch 修復核心：複習卡不再是「互動卡 + deck 預覽」雙軌結構，而是
// 兩個**固定 identity、永久存活**的 slot（slot = currentIndex % 2）。每個 slot
// 渲染完整卡骨架於全尺寸；縮放 / 位移 / 旋轉 / 透明度 = `f(role, dismissProgress)`
// 純函數（Animatable 值 diff）。promote = settle transaction 內翻轉 role —
// incoming slot 的 transform 早已被 fling 動畫推到 active 值、內容 index 不變
// → 零內容 diff、零 _makeView，只有 hit-testing gate 翻面。
//
// 本檔只放純邏輯（role 指派 + transform 公式），由
// TodayReviewCardSlotTests 窮舉驗證；view 組裝在 TodayReviewSwipeDeck.swift。

// MARK: Role / Assignment

enum TodayReviewCardSlotRole: Equatable {
    /// 前景互動卡：追手指、可點、承載 reveal fold。
    case active
    /// 底卡預覽：縮小墊底，fling 期間隨 dismissProgress 升頂。
    case preview
    /// 不可見（隊尾無下一張 / completion / 空 queue）。幾何與 preview 同源、
    /// 僅透明度 0 —— 重新出場永遠是值 diff，不是結構 insert。
    case hidden
}

struct TodayReviewCardSlotAssignment: Equatable {
    let role: TodayReviewCardSlotRole
    /// 此 slot 應渲染的 queue index。hidden 時 clamp 到當前卡，
    /// 讓「進入 / 離開隊尾」不換內容（值穩定）。
    let cardIndex: Int
}

/// Slot 指派與 transform 的單一真相 — total function，任何輸入不 crash。
enum TodayReviewCardSlotLayout {
    static let slotCount = 2

    /// 舊 stackCard depth-1 的縮放階差（每層 0.025）。
    static let stackDepthScaleStep: CGFloat = 0.025
    /// 舊 stackCard depth-1 的 Y 位移階差（每層 5pt）。
    static let stackDepthYStep: CGFloat = 5

    /// active slot = currentIndex % 2（負值防禦性取模）。
    static func activeSlot(currentIndex: Int) -> Int {
        ((currentIndex % slotCount) + slotCount) % slotCount
    }

    /// slot 內容指派 — 純推導自 (currentIndex, queueCount)：
    /// - active slot 渲染 currentIndex
    /// - 另一 slot：有下一張 → preview(currentIndex+1)；隊尾 → hidden(clamp currentIndex)
    /// - completion / 空 queue / 越界 → 全 hidden（內容 clamp 至末卡）
    static func assignment(slot: Int, currentIndex: Int, queueCount: Int) -> TodayReviewCardSlotAssignment {
        guard queueCount > 0 else {
            return .init(role: .hidden, cardIndex: 0)
        }
        let clamped = min(max(currentIndex, 0), queueCount - 1)
        guard currentIndex >= 0, currentIndex < queueCount else {
            return .init(role: .hidden, cardIndex: clamped)
        }
        if slot == activeSlot(currentIndex: currentIndex) {
            return .init(role: .active, cardIndex: currentIndex)
        }
        let next = currentIndex + 1
        guard next < queueCount else {
            return .init(role: .hidden, cardIndex: currentIndex)
        }
        return .init(role: .preview, cardIndex: next)
    }

    // MARK: Transform

    /// slot 的視覺姿態 — 全部是可插值的純值（結構永不變）。
    struct Transform: Equatable {
        var scale: CGFloat
        var xOffset: CGFloat
        var yOffset: CGFloat
        var rotationDegrees: Double
        /// 整層透明度（active 套舊互動卡公式；preview 套舊 depth-1 層公式）。
        var opacity: Double
    }

    /// 姿態純函數。促成 promote 零視覺 diff 的數學前提（由 unit test 釘死）：
    /// `transform(.preview, dismissProgress: 1) == transform(.active, swipeOffset: 0)`。
    ///
    /// - `swipeOffset`：僅 active 消費（追手指 / fling 飛出）。
    /// - `dismissProgress`：僅 preview / hidden 消費（升頂內插）。
    /// - `stackRotation`：preview / hidden 的隨機微旋轉（舊 stackRotations[0]）。
    /// - `introProgress`：僅 active 消費 — 取代舊 `.reviewCardPromote` insertion
    ///   transition 的「首插入升起」動畫（0 = promote 起始姿態、1 = identity）。
    static func transform(
        role: TodayReviewCardSlotRole,
        swipeOffset: CGFloat,
        dismissProgress: CGFloat,
        stackRotation: Double,
        screenWidth: CGFloat,
        introProgress: CGFloat
    ) -> Transform {
        switch role {
        case .active:
            let width = max(screenWidth, 1)
            return Transform(
                scale: TodayReviewMetrics.promoteScale
                    + (1 - TodayReviewMetrics.promoteScale) * introProgress,
                xOffset: swipeOffset,
                yOffset: TodayReviewMetrics.promoteYOffset * (1 - introProgress),
                rotationDegrees: Double(swipeOffset) / Double(width) * TodayReviewMetrics.swipeMaxRotation,
                opacity: 1.0 - Double(abs(swipeOffset)) / Double(width) * (1.0 - TodayReviewMetrics.swipeOpacityFloor)
            )
        case .preview, .hidden:
            // 舊 stackCard depth-1 公式：effectiveDepth = 1 × (1 - progress)。
            let effectiveDepth = 1.0 - dismissProgress
            let base = TodayReviewMetrics.cardBorderActiveOpacity
            let layerOpacity = base + (1.0 - base) * Double(dismissProgress)
            return Transform(
                scale: 1.0 - effectiveDepth * stackDepthScaleStep,
                xOffset: 0,
                yOffset: effectiveDepth * stackDepthYStep,
                rotationDegrees: stackRotation * Double(1.0 - dismissProgress),
                opacity: role == .hidden ? 0 : layerOpacity
            )
        }
    }

    /// 卡片邊框線條透明度 — preview 從 idle 0.45 內插到 active 0.72，
    /// 消滅舊雙軌（stackCard stroke 0.45 vs ReviewFoldSurface stroke 0.72）
    /// 在 settle swap 瞬間的邊框 pop。
    static func borderOpacity(role: TodayReviewCardSlotRole, dismissProgress: CGFloat) -> Double {
        switch role {
        case .active:
            return TodayReviewMetrics.cardBorderActiveOpacity
        case .preview, .hidden:
            return TodayReviewMetrics.cardBorderOpacity
                + (TodayReviewMetrics.cardBorderActiveOpacity - TodayReviewMetrics.cardBorderOpacity)
                * Double(dismissProgress)
        }
    }
}

// MARK: - Slot Model（presenter state 投影）

/// 一個 slot 的渲染輸入：指派 + 已備妥的卡內容。
/// 由 `TodayReviewState.presenterState` 投影（真 session），或 fixture adapter 合成。
struct TodayReviewCardSlotModel {
    let assignment: TodayReviewCardSlotAssignment
    let card: TodayReviewPresenterState.CurrentCard?

    /// 以 Layout 指派構造完整 slot 陣列；`card` provider 只會收到有效 queue index。
    static func make(
        currentIndex: Int,
        queueCount: Int,
        card: (Int) -> TodayReviewPresenterState.CurrentCard?
    ) -> [TodayReviewCardSlotModel] {
        (0..<TodayReviewCardSlotLayout.slotCount).map { slot in
            let assignment = TodayReviewCardSlotLayout.assignment(
                slot: slot,
                currentIndex: currentIndex,
                queueCount: queueCount
            )
            let inRange = assignment.cardIndex >= 0 && assignment.cardIndex < queueCount
            return .init(assignment: assignment, card: inRange ? card(assignment.cardIndex) : nil)
        }
    }
}
