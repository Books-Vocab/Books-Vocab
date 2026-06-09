//
//  NotebookPaletteTests.swift
//  Books & Vocab Tests
//
//  鎖 NotebookPalette.darken HSB 計算正確性。
//

import Foundation
import SwiftUI
import Testing
@testable import BooksAndVocab

#if canImport(UIKit)
import UIKit
private func hsb(_ color: Color) -> (h: CGFloat, s: CGFloat, b: CGFloat, a: CGFloat) {
    var h: CGFloat = 0, s: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
    UIColor(color).getHue(&h, saturation: &s, brightness: &b, alpha: &a)
    return (h, s, b, a)
}
#else
import AppKit
private func hsb(_ color: Color) -> (h: CGFloat, s: CGFloat, b: CGFloat, a: CGFloat) {
    var h: CGFloat = 0, s: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
    NSColor(color).usingColorSpace(.sRGB)?.getHue(&h, saturation: &s, brightness: &b, alpha: &a)
    return (h, s, b, a)
}
#endif

struct NotebookPaletteTests {
    @Test func darkenReducesBrightnessBy30Percent() async throws {
        let original = Color(hex: "#AFC2D3")!  // 海洋 Dusty Blue
        let darkened = NotebookPalette.darken(original, by: 0.3)
        let o = hsb(original)
        let d = hsb(darkened)
        #expect(abs(d.b - o.b * 0.7) < 0.01, "brightness should be ×0.7")
        #expect(abs(d.h - o.h) < 0.01, "hue should be preserved")
        #expect(abs(d.s - o.s) < 0.01, "saturation should be preserved")
    }

    @Test func darkenZeroIsIdentity() async throws {
        let original = Color(hex: "#DEC69C")!  // 琥珀
        let identity = NotebookPalette.darken(original, by: 0)
        let o = hsb(original)
        let i = hsb(identity)
        #expect(abs(i.b - o.b) < 0.001)
    }

    @Test func darkenAcrossAllMorandiColors() async throws {
        for (name, hex) in NotebookPalette.colors {
            guard let original = Color(hex: hex) else {
                Issue.record("\(name) (\(hex)) failed to parse")
                continue
            }
            let darkened = NotebookPalette.darken(original, by: 0.4)
            let o = hsb(original)
            let d = hsb(darkened)
            #expect(d.b < o.b, "\(name) brightness should decrease")
            #expect(abs(d.h - o.h) < 0.02, "\(name) hue should be near-preserved")
        }
    }
}
