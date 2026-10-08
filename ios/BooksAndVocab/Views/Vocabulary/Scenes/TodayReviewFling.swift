import CoreGraphics

// MARK: - Fling Transition（swipe 放手與按鈕 fling 的單一過渡規則 — 純邏輯）
//
// #2027：swipe 放手、按鈕、ReviewProbe 全部經 `plan` 得到同一組（終點、凍結 intensity、
// spring 時長），flingCard 只有一條 `withAnimation(AppMotion.swipeFling(duration:))`。
// - 凍結 intensity = 方向符號：按鈕按下當幀 toolbar 就有完整回饋（舊路徑凍結成 0）。
// - 時長只依「牌堆升頂還剩多少」連續放大：升頂已飽和的 swipe 放手 = 原 SwipeFling
//   （response 0.18），從 0 起算的按鈕最長 base × 1.6 —— 按鈕不再比 swipe 倉促。
// - dismissProgress 的 200pt 映射**刻意不改**：fling 期間 body 只以終值求值一次，
//   preview 的 transform 由 SwiftUI 沿同一條 spring 曲線插值，升層在時間上與 offset
//   同步，不會「前 40% 距離就飽和」；改映射只會改變拖動手感。
//
// 單元測試：TodayReviewFlingTests。view 組裝在 TodayReviewSwipeDeck.swift（flingCard）。

enum TodayReviewFling {

    /// dismissProgress 飽和的拖動距離（pt）：牌堆升頂在此完成。
    static let stackRiseDistance: CGFloat = 200
    /// 沒有手指速度的入口（按鈕 / probe）用來算飛出距離的名目速度（pt/s）。
    static let nominalReleaseVelocity: CGFloat = 1200
    /// 牌堆升頂全程都還沒走（按鈕）時，時長相對 baseDuration 的加成。
    static let remainingRiseDurationScale: Double = 0.6

    /// 甩出進度 (0=靜止, 1=完全離開) — 驅動牌堆同步升頂。拖動與 fling 同源。
    static func dismissProgress(swipeOffset: CGFloat) -> CGFloat {
        min(abs(swipeOffset) / stackRiseDistance, 1.0)
    }

    /// 一次 fling 的完整規劃。
    struct Plan: Equatable {
        /// swipeOffset 的終點（帶方向）。
        let targetOffset: CGFloat
        /// fling 期間凍結給 toolbar 的 swipeIntensity。
        let frozenIntensity: Double
        /// spring 時長（bounce 0）。
        let duration: Double
    }

    static func plan(
        direction: CGFloat,
        startOffset: CGFloat,
        releaseVelocity: CGFloat?,
        screenWidth: CGFloat,
        threshold: CGFloat,
        baseDuration: Double
    ) -> Plan {
        let sign: CGFloat = direction < 0 ? -1 : 1
        let velocity = max(releaseVelocity ?? nominalReleaseVelocity, 0)
        let distance = screenWidth * 1.3 + min(velocity / 2000, 0.5) * screenWidth * 0.4
        // 只計「沿飛出方向」已走的升頂；反向起點（拖右時按忘記）= 升頂從 0 起算。
        let progressed = dismissProgress(swipeOffset: max(startOffset * sign, 0))
        let remainingRise = Double(1 - progressed)
        return Plan(
            targetOffset: sign * distance,
            frozenIntensity: Double(sign),
            duration: baseDuration * (1 + remainingRiseDurationScale * remainingRise)
        )
    }

    /// toolbar 看到的 swipeIntensity。fling 期間與 settle 後「凍結值尚未歸零」的那一幀
    /// 都讀凍結值 —— settle 的 no-anim transaction 只放下 dismissPhase，凍結值由下一個
    /// runloop 以動畫歸零，toolbar 回饋因此平滑放鬆而不是被 no-anim 硬切。
    static func toolbarIntensity(
        animatingOut: Bool,
        frozen: Double,
        swipeEnabled: Bool,
        swipeOffset: CGFloat,
        threshold: CGFloat
    ) -> Double {
        if animatingOut || frozen != 0 { return frozen }
        guard swipeEnabled else { return 0 }
        return liveIntensity(swipeOffset: swipeOffset, threshold: threshold)
    }

    /// 拖動中的 swipeIntensity（−1…1，閾值飽和）。
    static func liveIntensity(swipeOffset: CGFloat, threshold: CGFloat) -> Double {
        max(-1, min(1, Double(swipeOffset / max(threshold, 1))))
    }

    /// 卡片上「記得 / 忘記」方向標記的不透明度（#2045）：沿 `direction` 的位移 / 閾值，
    /// 0 → 閾值線性漸入、飽和為 1，反方向恆 0（兩個標記常駐、只有值變，不用 if/else 切換）。
    /// 由 swipeOffset 直接推導（不經凍結的 toolbar intensity）：fling 時 offset 被 spring
    /// 推到終點，標記沿同一條曲線漸入（按鈕路徑也一樣）；回彈時沿 snap-back spring 淡出；
    /// settle 的 no-anim 內 offset 歸零 → 標記同幀歸 0，不留殘影。
    static func markerOpacity(swipeOffset: CGFloat, threshold: CGFloat, direction: CGFloat) -> Double {
        let sign: CGFloat = direction < 0 ? -1 : 1
        let along = max(swipeOffset * sign, 0)
        return Double(min(along / max(threshold, 1), 1))
    }
}
