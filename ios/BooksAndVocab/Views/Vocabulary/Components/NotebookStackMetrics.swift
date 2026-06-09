//
//  NotebookStackMetrics.swift
//  Books & Vocab
//
//  Notebook 立體堆卡（`NotebookStackedCoverView`）的 magic number 集中地。
//  對應 `docs/sop/ui-design.md` 規則：不可在 view 寫 magic number，
//  spacing/radius/elevation 數值先放 token namespace。
//
//  幾何由 plan「Notebook Editorial Stack」對齊：
//  - 全層 corner radius 走 `AppRadius.md`
//  - 層間 dy = `AppSpacing.s1` (4pt)，dx = `AppSpacing.s1` (4pt) 單側
//  - Ghost 改 cream paper（paperLight / paperSepia / paperSepiaDeep），
//    不再用 brightness shift（取代 `deckColor`）
//  - Editorial 手感：每層套 rotation + dx jitter，per-notebook deterministic seed
//  - press-in 僅頂層 offset，下層 ghost 微下沉；rotation 不參與動畫
//

import SwiftUI

enum NotebookStackMetrics {
    /// 依字數決定堆疊層數：
    /// - 0 = 平面單卡（empty notebook）
    /// - 1-50 = 薄堆（2 層）
    /// - 51-200 = 中堆（3 層）
    /// - 200+ = 厚堆（4 層，上限）
    static func layerCount(forCardCount n: Int) -> Int {
        switch n {
        case ..<1: return 1
        case 1...50: return 2
        case 51...200: return 3
        default: return 4
        }
    }

    /// 每層垂直位移（resting 狀態）
    static let layerOffsetY: CGFloat = AppSpacing.s1          // 4pt
    /// 每層水平單側 inset（下層比上層各縮 dx）
    static let layerInsetX: CGFloat = AppSpacing.s1           // 4pt

    // MARK: - Editorial imperfection（rotation + dx jitter）

    /// 每層基準 rotation（index = depth；0 = top cover）— degrees。
    /// 配合 `.bottom` anchor：底部錨定、頂部微張，模擬「桌上隨手疊」。
    static let layerRotations: [Double] = [0.5, -0.8, 1.5, -1.5]

    /// 每層 dx 額外 jitter（在 `layerInsetX` 之外加值）— pt。
    static let layerDxJitter: [CGFloat] = [0, 0.5, -1, 1]

    /// Rotation overhang 保守常數。
    /// 典型 cover width ~160pt × sin(1.5°) ≈ 4.2pt；8pt = 2× 安全邊際，
    /// 避免 GeometryReader 造成 grid layout 反覆。
    static let rotationOverhang: CGFloat = AppSpacing.s2      // 8pt

    /// Editorial pattern overlay opacity — `NotebookCoverPatterns` 6 種 pattern 統一引此 token。
    /// 取自既有 editorial stack PR tune 後 per-pattern 值的中位數 (0.10-0.15),
    /// 統一為 0.12 確保 serif name 為視覺主角(spec D1.1「pattern 不競爭」原則)。
    static let patternOpacity: Double = 0.12

    /// Per-notebook deterministic jitter — seed 由 caller 傳入（用 `stableSeed(for:)`）。
    /// 同一 seed × 同一 depth 永遠回傳同一 (angle, dx)，render 不會閃爍。
    /// 在 `layerRotations` / `layerDxJitter` base 上 ±50% 擾動。
    ///
    /// ⚠️ 不要傳 `String.hashValue` — Swift hashValue 每 process 啟動隨機 seeded，
    /// 會導致同一本 notebook 每次 app 開啟旋轉角度都不同。一律走 `stableSeed(for:)`。
    static func seedJitter(seed: Int, depth: Int) -> (angle: Double, dx: CGFloat) {
        let idx = min(max(depth, 0), layerRotations.count - 1)
        let baseAngle = layerRotations[idx]
        let baseDx = layerDxJitter[idx]
        // perturb ∈ [-0.5, +0.5]，依 seed × depth 變化。
        // abs() 確保負 seed 下 Swift `%` 仍回傳 [0, 99]，perturb 範圍 invariant。
        let mixed = abs(seed &+ depth &* 31) % 100
        let perturb = Double(mixed) / 100.0 - 0.5
        return (
            angle: baseAngle * (1.0 + perturb * 0.5),
            dx:    baseDx * (1.0 + CGFloat(perturb) * 0.5)
        )
    }

    /// Cross-launch stable hash (djb2) — 取代 `String.hashValue` 的 per-process random seed。
    /// 同一字串永遠回傳同一非負 Int，保證 rotation 跨 launch 不變。
    static func stableSeed(for string: String) -> Int {
        var hash: UInt64 = 5381
        for byte in string.utf8 {
            hash = (hash &* 33) &+ UInt64(byte)
        }
        // 截到正 Int 範圍（去最高位 sign bit），seedJitter `% 100` 始終非負
        return Int(hash & UInt64(Int.max))
    }

    // MARK: - Ghost color（cream paper, 取代 brightness-based deckColor）

    /// Ghost cream 紙頁三階 — index = depth (1/2/3)。
    /// depth 0 = top cover（不呼叫此函式）。
    /// Dark variant 待下輪 design 決定（spec 已留 hook，目前 light/dark 同色）。
    static func ghostPaperColor(depth: Int, scheme: ColorScheme) -> Color {
        _ = scheme  // dark variant pending; silence unused warning
        switch depth {
        case 1:  return AppColors.paperLight
        case 2:  return AppColors.paperSepia
        default: return AppColors.paperSepiaDeep  // depth >= 3
        }
    }

}
