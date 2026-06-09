//
//  AppSkinTierTests.swift
//  Books & Vocab Tests
//
//  Pins AppSkin.tierColor(for:) and tierLabel(for:) — the mapping from
//  backend tier strings to presentation colours and labels. A regression here
//  silently changes the visual identity of word difficulty across the app.
//

import SwiftUI
import Testing
@testable import BooksAndVocab

struct AppSkinTierTests {

    private let skin = AppSkin.themed(.light)

    // MARK: - tierColor

    @Test func coreTierReturnsSuccessColor() {
        let color = skin.tierColor(for: "core")
        #expect(color == skin.palette.success)
    }

    @Test func intermediateTierReturnsTierIntermediateColor() {
        let color = skin.tierColor(for: "intermediate")
        #expect(color == skin.palette.tierIntermediate)
    }

    @Test func advancedTierReturnsTierAdvancedColor() {
        let color = skin.tierColor(for: "advanced")
        #expect(color == skin.palette.tierAdvanced)
    }

    @Test func rareTierReturnsDestructiveColor() {
        let color = skin.tierColor(for: "rare")
        #expect(color == skin.palette.destructive)
    }

    @Test func unknownTierReturnsSecondaryText() {
        let color = skin.tierColor(for: "nonsense")
        #expect(color == skin.palette.secondaryText)
    }

    @Test func nilTierReturnsSecondaryText() {
        let color = skin.tierColor(for: nil)
        #expect(color == skin.palette.secondaryText)
    }

    @Test func emptyTierReturnsSecondaryText() {
        let color = skin.tierColor(for: "")
        #expect(color == skin.palette.secondaryText)
    }

    // MARK: - tierLabel

    @Test func coreLabelIsCore() {
        #expect(skin.tierLabel(for: "core") == "core")
    }

    @Test func intermediateLabelIsIntermediate() {
        #expect(skin.tierLabel(for: "intermediate") == "intermediate")
    }

    @Test func advancedLabelIsAdvanced() {
        #expect(skin.tierLabel(for: "advanced") == "advanced")
    }

    @Test func rareLabelIsRare() {
        #expect(skin.tierLabel(for: "rare") == "rare")
    }

    @Test func unknownLabelPassesThrough() {
        #expect(skin.tierLabel(for: "weird") == "weird")
    }

    @Test func nilLabelReturnsEmptyString() {
        #expect(skin.tierLabel(for: nil) == "")
    }

    @Test func emptyLabelReturnsEmptyString() {
        #expect(skin.tierLabel(for: "") == "")
    }
}
