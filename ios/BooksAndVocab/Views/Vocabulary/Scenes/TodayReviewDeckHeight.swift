import CoreGraphics

// MARK: - Deck Height Transition (卡片區高度過渡 — 純邏輯)
//
// 問題（#2026）：active slot 的 layout 高度是 `nil`（自然高度）、非 active slot
// cap 成固定值。`nil` ↔ 固定值不可插值，role 輪替瞬間卡片區高度硬切，連帶下方
// 「點一下展開」區位移。
//
// 解法：卡片區高度由**單一獨立的 CGFloat（`deckShellHeight`）**驅動，role 翻面時
// 以 `reviewNavigationSpring` 過渡一次；本檔只放「何時快閃、何時動畫、每個 slot
// 吃哪個高度」的純規則，view 組裝在 TodayReviewPresenter / TodayReviewSwipeDeck。
//
// 為何不是 `interpolated(from:to:progress:)` 這種「模型側插值」：重新指向（動畫
// 中途又換目標）時，@State 讀到的是 model 值（上一個目標），不是螢幕上的
// presentation 值；模型側插值會在中斷瞬間跳回舊目標。把單一 CGFloat 交給
// SwiftUI spring 才有速度連續的 retarget。純函數因此負責「規劃」而非「插值」。
//
// 單元測試：TodayReviewDeckHeightTests。

enum TodayReviewDeckHeight {

    /// 量測雜訊容忍（pt）。與既有 slotFrontHeights 去重門檻同值。
    static let epsilon: CGFloat = 0.5

    /// 一次目標變更的處置。
    enum Plan: Equatable {
        /// 已在目標（含：動畫中重新指向同一目標）—— 不做事。
        case hold
        /// 無動畫直接落到 `height`（啟動量測、答案已展開）。
        case snap(to: CGFloat)
        /// 以 spring 過渡到 `height`；起點永遠是螢幕上當下的高度（由 SwiftUI 保證）。
        case animate(to: CGFloat)
    }

    /// 規劃一次高度變更。
    ///
    /// 不變式（皆有單元測試）：
    /// - 同高（|Δ| ≤ ε）恆為 `.hold`（恆等）。
    /// - 終點恆等於 `target`（不會產生中間值；snap 與 animate 的終點都是 target）。
    /// - 啟動（displayed ≤ 0，尚無舊高度可插值）與目標無效（≤ 0）一律 snap。
    /// - 答案展開中不動畫（展開有自己的摺疊動畫，高度過渡與之打架）。
    static func plan(displayed: CGFloat, target: CGFloat, revealed: Bool) -> Plan {
        let t = max(target, 0)
        if abs(displayed - t) <= epsilon { return .hold }
        if revealed || displayed <= 0 || t <= 0 { return .snap(to: t) }
        return .animate(to: t)
    }

    /// 非 active slot 的 cap 與 depth-2 殼層吃的高度：過渡值；啟動期（過渡值尚未
    /// 建立）直接用量測目標，避免量測完成到 onChange 落地之間多出一幀 0 高。
    static func resolvedShell(shell: CGFloat, target: CGFloat) -> CGFloat {
        shell > 0 ? shell : max(target, 0)
    }

    /// slot 的 layout 高度（`nil` = 自然高度）。
    ///
    /// - 非 active：cap 到 `min(resolvedShell, target)`（FIX(review-flip-gap)：不撐高
    ///   ZStack；且從較高的舊高度收合時，背景卡不得比 active 卡更高而從底下探出）。
    /// - active：只有「過渡中」才釘成 `resolvedShell`；穩態與展開答案時回 `nil`，
    ///   自然高度負責摺疊增長。
    ///
    /// 恆有 cap(非 active) ≤ pin(active)：ZStack 高度永遠只由 active 決定。
    ///
    /// 「過渡中」= 動畫進行中（`inFlight`）**或** 模型值尚未追上目標
    /// （|shell − target| > ε，亦即剛翻 role、onChange 還沒啟動動畫的那一幀）。
    /// 後者保證 role 翻面當幀新 active 取的就是舊高度 → 零跳變。
    static func slotHeight(
        isActive: Bool,
        shell: CGFloat,
        target: CGFloat,
        inFlight: Bool,
        revealed: Bool
    ) -> CGFloat? {
        let resolved = resolvedShell(shell: shell, target: target)
        guard isActive else { return target > 0 ? min(resolved, target) : resolved }
        if revealed || shell <= 0 { return nil }
        let transitioning = inFlight || abs(shell - target) > epsilon
        return transitioning ? resolved : nil
    }

    /// slot 實測高度的寫入判定：回傳要寫入的新值，或 nil（無效 / 在雜訊內）。
    /// 比對對象是 **slot 自己上次記的值**，不是卡片的量測快取 —— 同一張卡的快取
    /// 高度不變，但 slot 內容輪替後 slot 存的是別張卡的舊值（stale，第三種跳法）。
    static func slotHeightUpdate(stored: CGFloat, measured: CGFloat) -> CGFloat? {
        guard measured > 0, abs(stored - measured) > epsilon else { return nil }
        return measured
    }
}
