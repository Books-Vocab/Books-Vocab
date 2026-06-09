//
//  ReviewGradientTests.swift
//  Books & Vocab Tests
//
//  Pins ReviewGradient — the ratio-to-color interpolation that drives the review
//  card heatmap. A regression here changes the visual meaning of "overdue" for
//  all users.
//

import SwiftUI
import Testing
@testable import BooksAndVocab

struct ReviewGradientTests {

    // MARK: - cssHex boundary values

    @Test func ratioZeroReturnsGreen() {
        let hex = ReviewGradient.cssHex(for: 0)
        // Stop at 0.00: HSL(160, 48, 38) → #328F70
        #expect(hex == "#328F70")
    }

    @Test func ratioOneReturnsYellow() {
        let hex = ReviewGradient.cssHex(for: 1.0)
        // Stop at 1.00: HSL(45, 55, 48) → #BD9C37
        #expect(hex == "#BD9C37")
    }

    @Test func ratioTwoReturnsRed() {
        let hex = ReviewGradient.cssHex(for: 2.0)
        // Stop at 2.00: HSL(4, 58, 40) → #A1322A
        #expect(hex == "#A1322A")
    }

    @Test func ratioThreeReturnsPurple() {
        let hex = ReviewGradient.cssHex(for: 3.0)
        // Stop at 3.00: HSL(278, 50, 34) → #622B82
        #expect(hex == "#622B82")
    }

    @Test func negativeRatioClampsToZero() {
        let hex = ReviewGradient.cssHex(for: -1.0)
        #expect(hex == ReviewGradient.cssHex(for: 0))
    }

    @Test func ratioBeyondMaxClampsToLastStop() {
        let hex5 = ReviewGradient.cssHex(for: 5.0)
        let hex3 = ReviewGradient.cssHex(for: 3.0)
        #expect(hex5 == hex3)
    }

    // MARK: - Interpolation between stops

    @Test func ratioMidpointBetweenStopsInterpolates() {
        // Between 0.00 and 0.15, midpoint 0.075 should give a color between green stops
        let hex = ReviewGradient.cssHex(for: 0.075)
        // Should not equal either endpoint exactly
        #expect(hex != ReviewGradient.cssHex(for: 0.0))
        #expect(hex != ReviewGradient.cssHex(for: 0.15))
    }

    @Test func ratioOnePointFiveBetweenOrangeAndRed() {
        // Between 1.30 and 2.00
        let hex = ReviewGradient.cssHex(for: 1.5)
        #expect(hex != ReviewGradient.cssHex(for: 1.3))
        #expect(hex != ReviewGradient.cssHex(for: 2.0))
    }

    // MARK: - cssHex format

    @Test func cssHexAlwaysStartsWithHash() {
        for ratio in [0.0, 0.5, 1.0, 2.0, 3.0] {
            let hex = ReviewGradient.cssHex(for: ratio)
            #expect(hex.hasPrefix("#"), "ratio \(ratio) hex missing #: \(hex)")
        }
    }

    @Test func cssHexIsSevenCharacters() {
        for ratio in [0.0, 0.5, 1.0, 2.0, 3.0] {
            let hex = ReviewGradient.cssHex(for: ratio)
            #expect(hex.count == 7, "ratio \(ratio) hex length != 7: \(hex)")
        }
    }

    // MARK: - color(for:) non-nil

    @Test func colorForAnyRatioIsNonNil() {
        for ratio in [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0] {
            let color = ReviewGradient.color(for: ratio)
            // SwiftUI Color is opaque; we can only assert it doesn't crash
            _ = color
        }
    }

    // MARK: - Monotonic hue progression (sanity)

    @Test func hueProgressesFromGreenToYellowToRed() {
        // Approximate hue check via cssHex: green → yellow → red should be distinct
        let green = ReviewGradient.cssHex(for: 0.0)
        let yellow = ReviewGradient.cssHex(for: 1.0)
        let red = ReviewGradient.cssHex(for: 2.0)

        #expect(green != yellow)
        #expect(yellow != red)
        #expect(green != red)
    }
}
