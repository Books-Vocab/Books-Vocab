//
//  AppFonts.swift
//  BooksBrowser
//
//  統一的字體排印 (Design System Tokens)
//  Serif: Athelas (EN) + STSongti-TC (CJK cascade)
//  Mono:  ElmsSans (EN) + system monospaced (CJK fallback)
//

import SwiftUI
import UIKit

enum AppFonts {

    // MARK: - Font Builders

    private static let cascadeListKey = UIFontDescriptor.AttributeName(
        rawValue: "NSCTFontCascadeListAttribute"
    )

    /// Serif: Athelas + STSongti-TC cascade
    static func serif(size: CGFloat, bold: Bool = false) -> Font {
        let primary = bold ? "Athelas-Bold" : "Athelas-Regular"
        let fallback = bold ? "STSongti-TC-Bold" : "STSongti-TC-Regular"
        let base = UIFontDescriptor(fontAttributes: [.name: primary])
        let cjk = UIFontDescriptor(fontAttributes: [.name: fallback])
        let descriptor = base.addingAttributes([cascadeListKey: [cjk]])
        return Font(UIFont(descriptor: descriptor, size: size) as CTFont)
    }

    /// Mono: ElmsSans + system monospaced cascade
    static func mono(size: CGFloat, bold: Bool = false) -> Font {
        let primary = bold ? "ElmsSans-Bold" : "ElmsSans-Regular"
        let sysMono = UIFont.monospacedSystemFont(
            ofSize: size, weight: bold ? .bold : .regular
        ).fontDescriptor
        let base = UIFontDescriptor(fontAttributes: [.name: primary])
        let descriptor = base.addingAttributes([cascadeListKey: [sysMono]])
        return Font(UIFont(descriptor: descriptor, size: size) as CTFont)
    }

    // MARK: - 標題層級 (Headers)

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

    // MARK: - 內文層級 (Body)

    /// 預設內文 — 17pt serif
    static func body(weight: Font.Weight = .regular) -> Font {
        serif(size: 17, bold: weight.isBold)
    }

    /// 次要說明 — 15pt serif
    static func subhead(weight: Font.Weight = .regular) -> Font {
        serif(size: 15, bold: weight.isBold)
    }

    // MARK: - 細節層級 (Caption & Mono)

    /// 提示小字 — 12pt serif
    static func caption(weight: Font.Weight = .regular) -> Font {
        serif(size: 12, bold: weight.isBold)
    }

    /// 極小提示 — 11pt serif
    static func caption2(weight: Font.Weight = .regular) -> Font {
        serif(size: 11, bold: weight.isBold)
    }

    /// 等寬數字 — ElmsSans mono
    static func monoNumbers(size: CGFloat = 14) -> Font {
        mono(size: size)
    }

    /// Reader 進度條等寬細字 — 11pt ElmsSans mono
    static func monoProgress() -> Font {
        mono(size: 11)
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
