//
//  AppFonts.swift
//  BooksBrowser
//
//  統一的字體排印 (Design System Tokens)
//

import SwiftUI

/// 建立 iOS 26 "Poetic Style" 所需的文字層級與字距設定
enum AppFonts {
    // ── 標題層級 (Headers) ──────────────────────────────────────────────────
    // 使用預設的系統字型或自訂 Serif 字型，微調 Tracking 營造張力
    
    /// 大型英雄標題
    static func hero(weight: Font.Weight = .semibold) -> Font {
        .system(size: 40, weight: weight, design: .serif)
    }
    
    /// 頁面主標題
    static func h1(weight: Font.Weight = .medium) -> Font {
        .system(size: 28, weight: weight, design: .serif)
    }
    
    /// 區塊標題
    static func h2(weight: Font.Weight = .medium) -> Font {
        .system(size: 22, weight: weight, design: .default)
    }
    
    // ── 內文層級 (Body) ────────────────────────────────────────────────────
    
    /// 預設清晰內文 (等同於標準 Body，但可以統一管理)
    static func body(weight: Font.Weight = .regular) -> Font {
        .system(.body, design: .default).weight(weight)
    }
    
    /// 次要說明文字 (Subheadline)
    static func subhead(weight: Font.Weight = .regular) -> Font {
        .system(.subheadline, design: .default).weight(weight)
    }
    
    // ── 細節層級 (Caption & Mono) ─────────────────────────────────────────
    
    /// 提示小字
    static func caption(weight: Font.Weight = .regular) -> Font {
        .system(.caption, design: .default).weight(weight)
    }
    
    /// 極小的提示字
    static func caption2(weight: Font.Weight = .regular) -> Font {
        .system(.caption2, design: .default).weight(weight)
    }
    
    /// 用於資料展示、進度條的等寬數字 (Poetic style 強調數字的俐落)
    static func monoNumbers(size: CGFloat = 14) -> Font {
        .system(size: size, weight: .regular, design: .monospaced)
    }

    /// 用於 Reader 進度條的等寬細字（11pt light monospaced）
    static func monoProgress() -> Font {
        .system(size: 11, weight: .light, design: .monospaced)
    }
}
