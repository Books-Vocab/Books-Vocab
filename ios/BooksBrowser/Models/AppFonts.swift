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
                DispatchQueue.main.async {
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
