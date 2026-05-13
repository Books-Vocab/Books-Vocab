//
//  AppFonts.swift
//  BooksBrowser
//
//  統一的字體排印 (Design System Tokens)
//  Serif:  Athelas (EN) + STSongti-TC (CJK cascade)  — 標題用
//  Sans:   ElmsSans (EN) + PingFang TC (CJK cascade)  — 內文用
//  Mono:   ElmsSans (EN) + system monospaced (CJK fallback)
//

import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif
import CoreText
import os

extension Notification.Name {
    static let serifCJKFontDidBecomeAvailable = Notification.Name("serifCJKFontDidBecomeAvailable")
}

@Observable
final class FontAvailabilityTracker {
    var serifCJKVersion: Int = 0

    private var observer: Any?

    init() {
        observer = NotificationCenter.default.addObserver(
            forName: .serifCJKFontDidBecomeAvailable,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            VocabSkin.invalidateTypographyCache()
            self?.serifCJKVersion += 1
        }
    }

    deinit {
        if let observer { NotificationCenter.default.removeObserver(observer) }
    }
}

enum AppFonts {

    // MARK: - Font Builders

    private static func platformFont(descriptor: PlatformFontDescriptor, size: CGFloat) -> PlatformFont {
        #if os(iOS)
        return PlatformFont(descriptor: descriptor, size: size)
        #elseif os(macOS)
        return PlatformFont(descriptor: descriptor, size: size) ?? PlatformFont.systemFont(ofSize: size)
        #endif
    }

    private static let cascadeListKey = PlatformFontDescriptor.AttributeName(
        rawValue: "NSCTFontCascadeListAttribute"
    )

    /// Serif: Athelas + STSongti-TC cascade
    static func serif(size: CGFloat, bold: Bool = false) -> Font {
        let primary = bold ? "Athelas-Bold" : "Athelas-Regular"
        let fallback = bold ? "STSongti-TC-Bold" : "STSongti-TC-Regular"
        let base = PlatformFontDescriptor(fontAttributes: [.name: primary])
        let cjk = PlatformFontDescriptor(fontAttributes: [.name: fallback])
        let descriptor = base.addingAttributes([cascadeListKey: [cjk]])
        return Font(platformFont(descriptor: descriptor, size: size) as CTFont)
    }

    /// Sans: ElmsSans + PingFang TC cascade
    static func sans(size: CGFloat, bold: Bool = false) -> Font {
        let primary = bold ? "ElmsSans-Bold" : "ElmsSans-Regular"
        let fallback = bold ? "PingFangTC-Semibold" : "PingFangTC-Regular"
        let base = PlatformFontDescriptor(fontAttributes: [.name: primary])
        let cjk = PlatformFontDescriptor(fontAttributes: [.name: fallback])
        let descriptor = base.addingAttributes([cascadeListKey: [cjk]])
        return Font(platformFont(descriptor: descriptor, size: size) as CTFont)
    }

    /// Mono: ElmsSans + system monospaced cascade
    static func mono(size: CGFloat, bold: Bool = false) -> Font {
        let primary = bold ? "ElmsSans-Bold" : "ElmsSans-Regular"
        let sysMono = PlatformFont.monospacedSystemFont(
            ofSize: size, weight: bold ? .bold : .regular
        ).fontDescriptor
        let base = PlatformFontDescriptor(fontAttributes: [.name: primary])
        let descriptor = base.addingAttributes([cascadeListKey: [sysMono]])
        return Font(platformFont(descriptor: descriptor, size: size) as CTFont)
    }

    // MARK: - Display 層級 (Brand / Hero) — serif

    /// 最大型品牌展示字 — 56pt serif，用於 launch / brand pages / 主要儀式感畫面
    /// 配合 tracking .tight 與 lineSpacing .display 使用
    ///
    /// 注意：Athelas/ElmsSans 目前只有 Regular + Bold 兩階字檔，
    /// `.medium / .semibold` 會 silently downgrade 為 Regular。
    /// 預設為 `.bold` 確保預設呼叫即得到真實 Bold 字面。
    static func display1(weight: Font.Weight = .bold) -> Font {
        serif(size: 56, bold: weight.isBold)
    }

    /// 次大型展示字 — 48pt serif，hero state、empty state 圖標下方主訊息
    /// （從 44pt 提到 48pt 拉開與 hero=40 的視覺差距，遵循 modular 1.2 ratio）
    static func display2(weight: Font.Weight = .bold) -> Font {
        serif(size: 48, bold: weight.isBold)
    }

    // MARK: - 標題層級 (Headers) — serif

    /// 大型英雄標題 — 40pt serif
    static func hero(weight: Font.Weight = .semibold) -> Font {
        serif(size: 40, bold: weight.isBold)
    }

    /// 頁面主標題 — 28pt serif
    static func h1(weight: Font.Weight = .medium) -> Font {
        serif(size: 28, bold: weight.isBold)
    }

    /// 區塊標題 — 22pt serif
    static func h2(weight: Font.Weight = .medium) -> Font {
        serif(size: 22, bold: weight.isBold)
    }

    // MARK: - 內文層級 (Body) — sans

    /// 預設內文 — 17pt sans
    static func body(weight: Font.Weight = .regular) -> Font {
        sans(size: 17, bold: weight.isBold)
    }

    /// 次要說明 — 15pt sans
    static func subhead(weight: Font.Weight = .regular) -> Font {
        sans(size: 15, bold: weight.isBold)
    }

    // MARK: - 細節層級 (Caption & Mono) — sans

    /// 提示小字 — 12pt sans
    static func caption(weight: Font.Weight = .regular) -> Font {
        sans(size: 12, bold: weight.isBold)
    }

    /// 極小提示 — 11pt sans
    static func caption2(weight: Font.Weight = .regular) -> Font {
        sans(size: 11, bold: weight.isBold)
    }

    /// 等寬內文 — 17pt ElmsSans mono（body 尺寸，用於音標、程式碼輸入等）
    static func mono() -> Font {
        mono(size: 17)
    }

    /// 等寬數字 — ElmsSans mono
    static func monoNumbers(size: CGFloat = 14) -> Font {
        mono(size: size)
    }

    /// Reader 進度條等寬細字 — 11pt ElmsSans mono
    static func monoProgress() -> Font {
        mono(size: 11)
    }

    // MARK: - Tracking Tokens (letter-spacing)
    // 在 SwiftUI 用 `.tracking(AppFonts.Tracking.tight)` 套用
    // 數值單位 pt（絕對 letter-spacing）

    enum Tracking {
        /// Display / hero 緊縮 — 配大字級降低視覺鬆散
        /// 在 56pt display1 上約 -0.021em，符合慣例
        static let tight: CGFloat = -1.2
        /// 標準字距
        static let normal: CGFloat = 0
        /// Body / metadata 微放寬
        static let wide: CGFloat = 0.3
        /// uppercase metadata 標籤（如「NEW」「BETA」），約 +0.07em on 12pt
        static let uppercase: CGFloat = 0.8
    }

    // MARK: - Line Spacing Tokens
    // 在 SwiftUI 用 `.lineSpacing(AppFonts.LineSpacing.body)` 套用
    // 數值為 SwiftUI `.lineSpacing(x)`：每行之外額外加 x pt 行距，
    // 真實 leading = font.lineHeight + x，不是固定行高倍率。

    enum LineSpacing {
        /// Display / hero — 0 額外行距，靠字體預設緊湊 leading
        static let display: CGFloat = 0
        /// 標題 — 微寬
        static let heading: CGFloat = 2
        /// 內文 — 舒適閱讀
        static let body: CGFloat = 4
        /// 長文閱讀 — 寬鬆
        static let reading: CGFloat = 6
        /// Caption — 略緊
        static let caption: CGFloat = 1
    }

    // MARK: - UIKit Fonts (for Appearance API)

    #if os(iOS)
    /// UIKit serif font — Athelas + STSongti-TC cascade
    static func uiSerif(size: CGFloat, bold: Bool = false) -> UIFont {
        let primary = bold ? "Athelas-Bold" : "Athelas-Regular"
        let fallback = bold ? "STSongti-TC-Bold" : "STSongti-TC-Regular"
        let base = UIFontDescriptor(fontAttributes: [.name: primary])
        let cjk = UIFontDescriptor(fontAttributes: [.name: fallback])
        let descriptor = base.addingAttributes([cascadeListKey: [cjk]])
        return UIFont(descriptor: descriptor, size: size)
    }

    /// UIKit sans font — ElmsSans + PingFang TC cascade
    static func uiSans(size: CGFloat, bold: Bool = false) -> UIFont {
        let primary = bold ? "ElmsSans-Bold" : "ElmsSans-Regular"
        let fallback = bold ? "PingFangTC-Semibold" : "PingFangTC-Regular"
        let base = UIFontDescriptor(fontAttributes: [.name: primary])
        let cjk = UIFontDescriptor(fontAttributes: [.name: fallback])
        let descriptor = base.addingAttributes([cascadeListKey: [cjk]])
        return UIFont(descriptor: descriptor, size: size)
    }

    /// 建立 serif 導航列 appearance（opaque + transparent pair）
    static func makeNavBarAppearances() -> (opaque: UINavigationBarAppearance, transparent: UINavigationBarAppearance) {
        let serifLarge = uiSerif(size: 34, bold: true)
        let serifInline = uiSerif(size: 17, bold: true)
        let largeTitleAttrs: [NSAttributedString.Key: Any] = [.font: serifLarge]
        let titleAttrs: [NSAttributedString.Key: Any] = [.font: serifInline]

        let opaque = UINavigationBarAppearance()
        opaque.configureWithDefaultBackground()
        opaque.largeTitleTextAttributes = largeTitleAttrs
        opaque.titleTextAttributes = titleAttrs

        let transparent = UINavigationBarAppearance()
        transparent.configureWithTransparentBackground()
        transparent.largeTitleTextAttributes = largeTitleAttrs
        transparent.titleTextAttributes = titleAttrs

        return (opaque, transparent)
    }

    /// 設定 UINavigationBar + UITabBar 全域字體
    static func configureGlobalAppearance() {
        let (_, transparent) = makeNavBarAppearances()
        UINavigationBar.appearance().standardAppearance = transparent
        UINavigationBar.appearance().compactAppearance = transparent
        UINavigationBar.appearance().scrollEdgeAppearance = transparent
        UINavigationBar.appearance().compactScrollEdgeAppearance = transparent

        let tabFont = uiSans(size: 10)
        let tabItemAppearance = UITabBarItemAppearance()
        tabItemAppearance.normal.titleTextAttributes = [.font: tabFont]
        tabItemAppearance.selected.titleTextAttributes = [.font: tabFont]

        let tabAppearance = UITabBarAppearance()
        tabAppearance.configureWithDefaultBackground()
        tabAppearance.stackedLayoutAppearance = tabItemAppearance
        tabAppearance.inlineLayoutAppearance = tabItemAppearance
        tabAppearance.compactInlineLayoutAppearance = tabItemAppearance
        UITabBar.appearance().standardAppearance = tabAppearance
        UITabBar.appearance().scrollEdgeAppearance = tabAppearance
    }
    #endif

    // MARK: - On-Demand Font Download

    /// 觸發 STSongti-TC 按需下載（系統字體，首次使用時需下載）
    /// 在 App 啟動時呼叫一次即可，已下載過則立即返回。
    static func ensureSerifCJKAvailable() {
        let fontNames = ["STSongti-TC-Regular", "STSongti-TC-Bold"]
        var descriptors: [PlatformFontDescriptor] = []

        for name in fontNames {
            let desc = PlatformFontDescriptor(fontAttributes: [.name: name])
            // 檢查是否已可用
            let ctDesc = desc as CTFontDescriptor
            if CTFontDescriptorCopyAttribute(ctDesc, kCTFontURLAttribute) != nil {
                continue  // 已存在，跳過
            }
            descriptors.append(desc)
        }

        guard !descriptors.isEmpty else { return }

        let cfArray = descriptors as CFArray
        CTFontDescriptorMatchFontDescriptorsWithProgressHandler(cfArray, nil) { state, _ in
            switch state {
            case .didFinish:
                AppLog.fonts.info("STSongti-TC download completed")
                Task { @MainActor in
                    NotificationCenter.default.post(name: .serifCJKFontDidBecomeAvailable, object: nil)
                }
            case .didFailWithError:
                AppLog.fonts.error("STSongti-TC download failed")
            default:
                break
            }
            return true  // 繼續下載
        }
    }
}

private extension Font.Weight {
    var isBold: Bool {
        switch self {
        case .medium, .semibold, .bold, .heavy, .black:
            return true
        default:
            return false
        }
    }
}
