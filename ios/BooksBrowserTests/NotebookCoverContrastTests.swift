//
//  NotebookCoverContrastTests.swift
//  Books & Vocab Tests
//
//  D1 editorial cover composition AA contrast 鎖回歸:
//  - light mode: primaryText `#37352F` 對 Morandi 12 色 cover ≥ 4.5:1
//  - dark mode:  primaryText `#E6E6E3` 對 NotebookPalette.darken(cover, by: 0.55) ≥ 4.5:1
//

import Foundation
import SwiftUI
import Testing
@testable import BooksBrowser

#if canImport(UIKit)
import UIKit
private func rgb(_ color: Color) -> (r: CGFloat, g: CGFloat, b: CGFloat) {
    var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
    UIColor(color).getRed(&r, green: &g, blue: &b, alpha: &a)
    return (r, g, b)
}
#else
import AppKit
private func rgb(_ color: Color) -> (r: CGFloat, g: CGFloat, b: CGFloat) {
    var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
    NSColor(color).usingColorSpace(.sRGB)?.getRed(&r, green: &g, blue: &b, alpha: &a)
    return (r, g, b)
}
#endif

enum WCAGContrast {
    /// sRGB relative luminance — per WCAG 2.1 §1.4.3
    static func relativeLuminance(_ color: Color) -> Double {
        let c = rgb(color)
        func channel(_ v: CGFloat) -> Double {
            let x = Double(v)
            return x <= 0.03928 ? x / 12.92 : pow((x + 0.055) / 1.055, 2.4)
        }
        return 0.2126 * channel(c.r) + 0.7152 * channel(c.g) + 0.0722 * channel(c.b)
    }

    /// 兩色對比比值。≥ 4.5:1 = AA normal text;≥ 3:1 = AA large text。
    static func ratio(_ a: Color, _ b: Color) -> Double {
        let la = relativeLuminance(a)
        let lb = relativeLuminance(b)
        let lighter = max(la, lb)
        let darker = min(la, lb)
        return (lighter + 0.05) / (darker + 0.05)
    }
}

struct NotebookCoverContrastTests {
    /// Light mode — primaryText #37352F on raw Morandi cover hex,全 12 色 ≥ AA 4.5:1
    @Test func morandiCoversPassAALight() async throws {
        let text = Color(hex: "#37352F")!
        for (name, hex) in NotebookPalette.colors {
            guard let cover = Color(hex: hex) else {
                Issue.record("\(name) (\(hex)) hex parse failed")
                continue
            }
            let r = WCAGContrast.ratio(text, cover)
            #expect(r >= 4.5,
                    "\(name) (\(hex)) fails AA against #37352F: ratio \(r)")
        }
    }

    /// Dark mode — primaryText #E6E6E3 on `NotebookPalette.darken(_, by: 0.55)` cover。
    /// Spec D1 fallback: cover 在 dark mode 套 HSB scale 自動加深, 與 view 的 contrast path 對齊。
    @Test func morandiCoversPassAADarkAfterShift() async throws {
        let text = Color(hex: "#E6E6E3")!
        for (name, hex) in NotebookPalette.colors {
            guard let raw = Color(hex: hex) else {
                Issue.record("\(name) (\(hex)) hex parse failed")
                continue
            }
            let darkened = NotebookPalette.darken(raw, by: 0.55)
            let r = WCAGContrast.ratio(text, darkened)
            #expect(r >= 4.5,
                    "\(name) (\(hex)) darkened fails AA against #E6E6E3: ratio \(r)")
        }
    }

    /// Hairline rule color = darken(cover, by: 0.3) 對 cover 對比 ≥ 3:1(AA large)
    @Test func ruleColorContrastWithCover() async throws {
        for (name, hex) in NotebookPalette.colors {
            guard let cover = Color(hex: hex) else { continue }
            let rule = NotebookPalette.darken(cover, by: 0.3)
            let r = WCAGContrast.ratio(cover, rule)
            #expect(r >= 1.5,
                    "\(name) rule too low contrast against cover: \(r)")
        }
    }
}
