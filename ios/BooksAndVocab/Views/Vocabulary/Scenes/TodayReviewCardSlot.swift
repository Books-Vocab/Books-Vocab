import SwiftUI

// MARK: - Resident Card Slots (Phase 4：三 slot 連續堆疊)
//
// Settle hitch / 深度 pop 修復核心：複習卡是三個**固定 identity、永久存活**
// 的 slot（slot = currentIndex % 3）。每個 slot 渲染完整卡骨架於全尺寸；
// 縮放 / 位移 / 旋轉 / 透明度 = `f(role, dismissProgress)` 純函數
// （Animatable 值 diff）。fling 期間 preview 升頂、underPreview 升至
// depth-1；settle transaction 內只翻 role —— 兩個存活 slot 的內容 index
// 不變（零內容 diff、零 _makeView），唯一的內容 diff 落在被回收、沉到
// 最深層 depth-2 的舊 active slot（被殼層位置遮蔽，幾不可見）。
//
// 本檔只放純邏輯（role 指派 + transform 公式），由
// TodayReviewCardSlotTests 窮舉驗證；view 組裝在 TodayReviewSwipeDeck.swift。

// MARK: Role / Assignment

enum TodayReviewCardSlotRole: Equatable {
    /// 前景互動卡：追手指、可點、承載 reveal fold。
    case active
    /// 底卡預覽（depth-1）：縮小墊底，fling 期間隨 dismissProgress 升頂。
    case preview
    /// 最深底卡（depth-2）：fling 期間隨 dismissProgress 升至 depth-1 ——
    /// settle 後深度堆疊不再出現「空窗 → 補卡」的 pop。
    case underPreview
    /// 不可見（隊尾不足三張 / completion / 空 queue）。幾何與 underPreview
    /// 同源、僅透明度 0 —— 重新出場永遠從最深層浮現，值 diff 不跳位。
    case hidden
}

struct TodayReviewCardSlotAssignment: Equatable {
    let role: TodayReviewCardSlotRole
    /// 此 slot 應渲染的 queue index。hidden 時 clamp 到 min(後繼目標, 末卡)，
    /// 讓「進入 / 離開隊尾」與 demote 路徑不換內容（值穩定）。
    let cardIndex: Int
}

/// Slot 指派與 transform 的單一真相 — total function，任何輸入不 crash。
enum TodayReviewCardSlotLayout {
    static let slotCount = 3

    /// 舊 stackCard depth-1 的縮放階差（每層 0.025）。
    static let stackDepthScaleStep: CGFloat = 0.025
    /// 舊 stackCard depth-1 的 Y 位移階差（每層 5pt）。
    static let stackDepthYStep: CGFloat = 5

    /// active slot = currentIndex % 3（負值防禦性取模）。
    static func activeSlot(currentIndex: Int) -> Int {
        ((currentIndex % slotCount) + slotCount) % slotCount
    }

    /// slot 內容指派 — 純推導自 (currentIndex, queueCount)：
    /// - active slot 渲染 currentIndex
    /// - preview 後繼 slot（activeSlot(i+1)）：有下一張 → preview(i+1)
    /// - underPreview 後繼 slot（activeSlot(i+2)）：有第三張 → underPreview(i+2)
    /// - 目標越界 → hidden，內容 clamp = min(target, queueCount-1)：推進時
    ///   demote 路徑（underPreview → preview 後繼）即使翻 hidden 內容也不變
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
        let isPreviewSuccessor = slot == activeSlot(currentIndex: currentIndex + 1)
        let target = currentIndex + (isPreviewSuccessor ? 1 : 2)
        guard target < queueCount else {
            return .init(role: .hidden, cardIndex: min(target, queueCount - 1))
        }
        return .init(role: isPreviewSuccessor ? .preview : .underPreview, cardIndex: target)
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

    /// 姿態純函數。促成 settle 零視覺 diff 的兩道數學前提（由 unit test 釘死）：
    /// `transform(.preview, dismissProgress: 1) == transform(.active, swipeOffset: 0)`
    /// `transform(.underPreview, dismissProgress: 1) == transform(.preview, dismissProgress: 0)`
    ///
    /// 非 active 一律走同一條線性 depth 公式（effectiveDepth = depthBase −
    /// dismissProgress；preview depthBase=1、underPreview/hidden depthBase=2），
    /// 邊界連續性由公式本身保證，不靠常數對齊。
    ///
    /// - `swipeOffset`：僅 active 消費（追手指 / fling 飛出）。
    /// - `dismissProgress`：preview / underPreview / hidden 消費（升層內插）。
    /// - `stackRotation`：底卡的隨機微旋轉（per-slot 持久，見 stackRotations）。
    ///   只在 depth < 1（preview → active 最後一段）衰減；深層恆全量，
    ///   underPreview → preview 的 rotation 才能跨 settle 連續。
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
        case .preview, .underPreview, .hidden:
            let depthBase: CGFloat = role == .preview ? 1 : 2
            let effectiveDepth = depthBase - dismissProgress
            // 線性外推舊 depth-1 層透明度（depth 0 → 1.0、depth 1 → 0.72）。
            let base = TodayReviewMetrics.cardBorderActiveOpacity
            let layerOpacity = max(0, 1.0 - (1.0 - base) * Double(effectiveDepth))
            return Transform(
                scale: 1.0 - effectiveDepth * stackDepthScaleStep,
                xOffset: 0,
                yOffset: effectiveDepth * stackDepthYStep,
                rotationDegrees: stackRotation * Double(min(effectiveDepth, 1)),
                opacity: role == .hidden ? 0 : layerOpacity
            )
        }
    }

    /// 卡片邊框線條透明度 — 同一條線性 depth 公式（depth 0 → 0.72、depth 1 →
    /// 0.45、depth 2 沿線外推），消滅 settle swap 瞬間的邊框 pop；
    /// underPreview@1 == preview@0 的連續性由公式保證。
    static func borderOpacity(role: TodayReviewCardSlotRole, dismissProgress: CGFloat) -> Double {
        switch role {
        case .active:
            return TodayReviewMetrics.cardBorderActiveOpacity
        case .preview, .underPreview, .hidden:
            let depthBase: Double = role == .preview ? 1 : 2
            let effectiveDepth = depthBase - Double(dismissProgress)
            return max(0, TodayReviewMetrics.cardBorderActiveOpacity
                - (TodayReviewMetrics.cardBorderActiveOpacity - TodayReviewMetrics.cardBorderOpacity)
                * effectiveDepth)
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
