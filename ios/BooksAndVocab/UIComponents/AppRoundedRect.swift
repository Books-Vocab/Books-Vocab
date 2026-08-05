//
//  AppRoundedRect.swift
//  Books & Vocab
//
//  全 app 唯一的圓角矩形。圓角不是絕對長度，而是由無因次的 roundness `t`
//  在 render 當下從元件自己的 box 導出：
//
//      r = t · min(W, H) / 2 ,   0 ≤ t ≤ 1
//
//  t = 0 是直角；t = 1 讓圓角吃滿短邊的一半。t = 1 **不**退化成正圓或圓弧膠囊
//  ——曲率全程走 `.continuous`，端點是方圓。這是產品決定，不是實作限制。
//
//  為什麼用相對值：絕對半徑套在不同尺寸的元件上會給出不一致的視覺圓度
//  （同一個 8pt 在 44pt 高的 banner 上是 t=0.36，在 227pt 的清單卡上是 t=0.07）。
//  單自由度把這個反比拉平，代價是長卡片會比短卡片圓——這是刻意接受的。
//
//  半徑值一律走 `AppRoundness` / `skin.roundness` token，不在 view 寫裸數字。
//

import SwiftUI

struct AppRoundedRect: Shape, InsettableShape {
    /// 無因次圓度 t ∈ [0, 1]。超界會被 clamp，不會反向或溢出。
    var roundness: CGFloat

    private var insetAmount: CGFloat = 0

    init(roundness: CGFloat) {
        self.roundness = roundness
    }

    /// render 當下的實際角半徑（pt）。
    ///
    /// `rect` 是**未 inset 的原始 box**。inset 後半徑等距內縮（`r − d`）而非
    /// 重算比例（`t·(min−2d)/2`），因為 concentric 的定義就是等距——比例重算會讓
    /// 內圈角外凸，`.strokeBorder` 與巢狀容器的角落會不平行。
    /// 不需要再對 inset 後的 box 夾一次上限：因為 `t ≤ 1`，
    /// `t·base − inset ≤ base − inset`，而 `base − inset` 恰好就是 inset 後 box 的短邊一半。
    /// 也就是說半徑永遠不可能超出自己要畫的框——多夾一層是死碼。
    func radius(in rect: CGRect) -> CGFloat {
        let t = min(max(roundness, 0), 1)
        let base = min(rect.width, rect.height) / 2
        return max(0, t * base - insetAmount)
    }

    func path(in rect: CGRect) -> Path {
        let box = rect.insetBy(dx: insetAmount, dy: insetAmount)
        guard box.width > 0, box.height > 0 else { return Path() }
        return RoundedRectangle(cornerRadius: radius(in: rect), style: .continuous) // token-allow: 圓角平面的唯一實作
            .path(in: box)
    }

    func inset(by amount: CGFloat) -> AppRoundedRect {
        var copy = self
        copy.insetAmount += amount
        return copy
    }

    var animatableData: CGFloat {
        get { roundness }
        set { roundness = newValue }
    }
}

/// 上下緣圓度不同的變體（折疊列的接縫角、只圓上緣的卡片封面）。
///
/// 左右恆對稱——app 內 5 個 per-corner 場景全是水平對稱，多給兩個自由度只是
/// 徒增認知負擔。兩緣共用**同一個** `min(W, H) / 2` 基準，所以相同的 t 一定給出
/// 相同的半徑。
struct AppUnevenRoundedRect: Shape {
    var top: CGFloat
    var bottom: CGFloat

    /// 共用基準長度（pt）。`nil` = 用自己 box 的短邊，這是絕大多數情況。
    ///
    /// **只有一種情況要傳值：一個視覺物件被拆成多個 layout box 疊出來。**
    /// 比例制是「每個 box 各自導出半徑」，那對獨立元件是對的，但對摺頁卡這種
    /// 「一張卡切成 front + answer 兩段」的結構會壞掉——兩段高度不同，於是同一條
    /// 接縫的上下緣會算出不同半徑，外緣也會上下不對稱。這時基準必須來自**物件**
    /// 而不是**盒子**，由 caller 指定一個共用長度。
    var basis: CGFloat?

    /// 參數名刻意帶 `Roundness` 字樣：`ops/ui_token_lint.py` 的裸數字規則是靠
    /// 這個字尾認出「這是圓度平面」的。叫 `top:` / `bottom:` 會讓 pt 混進來卻無人攔。
    init(topRoundness: CGFloat, bottomRoundness: CGFloat, basis: CGFloat? = nil) {
        self.top = topRoundness
        self.bottom = bottomRoundness
        self.basis = basis
    }

    func topRadius(in rect: CGRect) -> CGFloat { radius(top, in: rect) }
    func bottomRadius(in rect: CGRect) -> CGFloat { radius(bottom, in: rect) }

    private func radius(_ roundness: CGFloat, in rect: CGRect) -> CGFloat {
        let t = min(max(roundness, 0), 1)
        let minorAxis = basis ?? min(rect.width, rect.height)
        // 即使 caller 給了共用基準，也不能畫出超過自己盒子的圓角。
        return min(t * minorAxis / 2, min(rect.width, rect.height) / 2)
    }

    func path(in rect: CGRect) -> Path {
        guard rect.width > 0, rect.height > 0 else { return Path() }
        let topR = topRadius(in: rect)
        let bottomR = bottomRadius(in: rect)
        return UnevenRoundedRectangle( // token-allow: per-corner 圓角的唯一實作
            topLeadingRadius: topR,
            bottomLeadingRadius: bottomR,
            bottomTrailingRadius: bottomR,
            topTrailingRadius: topR,
            style: .continuous
        ).path(in: rect)
    }

    var animatableData: AnimatablePair<CGFloat, CGFloat> {
        get { AnimatablePair(top, bottom) }
        set {
            top = newValue.first
            bottom = newValue.second
        }
    }
}
