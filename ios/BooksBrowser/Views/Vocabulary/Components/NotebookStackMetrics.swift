//
//  NotebookStackMetrics.swift
//  BooksBrowser
//
//  Notebook 立體堆卡（`NotebookStackedCoverView`）的 magic number 集中地。
//  對應 `docs/sop/ui-design.md` 規則：不可在 view 寫 magic number，
//  spacing/radius/elevation 數值先放 token namespace。
//
//  幾何由 plan「Notebooks 立體堆卡重構」對齊：
//  - 全層 corner radius 走 `AppRadius.md`
//  - 層間 dy = `AppSpacing.tinyGap` (3pt)，dx = `AppSpacing.s1` (4pt) 單側
//  - press-in 僅頂層 offset，下層 ghost 微下沉強化視差
//  - 色彩暗化走 HSB brightness，不動 saturation、不用 opacity
//

import SwiftUI

#if canImport(UIKit)
import UIKit
#elseif canImport(AppKit)
import AppKit
#endif

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

    /// 每層垂直位移（resting 狀態）— peek 需 ≥ 4pt 才在實機 @3x 清楚可辨
    static let layerOffsetY: CGFloat = AppSpacing.s1          // 4pt
    /// 每層水平單側 inset（下層比上層各縮 dx）
    static let layerInsetX: CGFloat = AppSpacing.s1           // 4pt
    /// Press-in 時頂層向上抽出的位移
    static let pressedTopOffsetY: CGFloat = -14
    /// Press-in 時每深一層額外下沉 1pt（強化視差，總幅 ≤ 2pt）
    static let pressedGhostOffsetY: CGFloat = 1
    /// Light mode 每深一層 brightness 遞減步階
    static let brightnessStepLight: CGFloat = 0.05
    /// Dark mode 每深一層 brightness 遞增步階（向亮走，避免黑底失辨識）
    static let brightnessStepDark: CGFloat = 0.08

    /// 依 colorScheme 對 base color 套深度 brightness shift。
    /// - depth 0 = 頂層（不動）
    /// - light: brightness 下降；dark: brightness 提升
    /// 不動 saturation（避免下層看起來「褪色」）。
    static func deckColor(_ base: Color, depth: Int, scheme: ColorScheme) -> Color {
        guard depth > 0 else { return base }
        let step = scheme == .dark ? brightnessStepDark : brightnessStepLight
        let direction: CGFloat = scheme == .dark ? +1 : -1
        let delta = direction * step * CGFloat(depth)
        return base.shiftingBrightness(by: delta)
    }
}

// MARK: - HSB brightness helper

extension Color {
    /// 以 HSB 模型平移 brightness（clamp 到 [0, 1]）。
    /// 透過 platform 原生 `UIColor` / `NSColor` 拆解；無法解析時回傳原色。
    fileprivate func shiftingBrightness(by delta: CGFloat) -> Color {
        #if canImport(UIKit)
        var h: CGFloat = 0, s: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        guard UIColor(self).getHue(&h, saturation: &s, brightness: &b, alpha: &a) else {
            return self
        }
        let newB = max(0, min(1, b + delta))
        return Color(hue: Double(h), saturation: Double(s), brightness: Double(newB), opacity: Double(a))
        #elseif canImport(AppKit)
        let ns = NSColor(self).usingColorSpace(.deviceRGB) ?? NSColor(self)
        var h: CGFloat = 0, s: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        ns.getHue(&h, saturation: &s, brightness: &b, alpha: &a)
        let newB = max(0, min(1, b + delta))
        return Color(hue: Double(h), saturation: Double(s), brightness: Double(newB), opacity: Double(a))
        #else
        return self
        #endif
    }
}
