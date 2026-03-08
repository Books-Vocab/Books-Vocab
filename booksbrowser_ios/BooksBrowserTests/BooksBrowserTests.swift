//
//  BooksBrowserTests.swift
//  BooksBrowserTests
//
//  Created by 陳亮宇 on 2026/2/24.
//

import Foundation
import Testing
@testable import BooksBrowser

struct BooksBrowserTests {
    @Test func readerBridgePlannerEmitsSingleWordHighlightCommand() async throws {
        var planner = ReadiumNavigatorView.Coordinator.BridgePlanner()
        let base = makeSnapshot(lookedUpWords: [])
        _ = planner.makeCommands(from: base)

        let commands = planner.makeCommands(from: makeSnapshot(lookedUpWords: ["resilient"]))

        #expect(commands.contains { command in
            if case .dom(.markNewVocabWord("resilient")) = command { return true }
            return false
        })
    }

    @Test func readerBridgePlannerClearsAndReappliesOnLargeRemoval() async throws {
        var planner = ReadiumNavigatorView.Coordinator.BridgePlanner()
        let originalWords = (0..<12).map { "word\($0)" }
        _ = planner.makeCommands(from: makeSnapshot(lookedUpWords: originalWords))

        let commands = planner.makeCommands(from: makeSnapshot(lookedUpWords: ["word1"]))

        #expect(commands.contains { command in
            if case .dom(.clearAllVocabHighlights) = command { return true }
            return false
        })
        #expect(commands.contains { command in
            if case .dom(.markVocabWords(let words)) = command {
                return words == ["word1"]
            }
            return false
        })
    }

    @Test func readerBridgePlannerOnlyClearsHighlightOncePerTrigger() async throws {
        var planner = ReadiumNavigatorView.Coordinator.BridgePlanner()
        let trigger = UUID()

        let first = planner.makeCommands(from: makeSnapshot(lookedUpWords: [], clearHighlightTrigger: trigger))
        let second = planner.makeCommands(from: makeSnapshot(lookedUpWords: [], clearHighlightTrigger: trigger))

        #expect(first.contains { command in
            if case .dom(.clearActiveHighlight) = command { return true }
            return false
        })
        #expect(second.contains { command in
            if case .dom(.clearActiveHighlight) = command { return true }
            return false
        } == false)
    }

    private func makeSnapshot(
        lookedUpWords: [String],
        clearHighlightTrigger: UUID = UUID(),
        underlineOpacity: Double = 0.22,
        showHitTestingDebug: Bool = false
    ) -> ReadiumNavigatorView.BridgeSnapshot {
        let configuration = ReaderViewConfiguration(
            paperColor: AppColors.paperSepia,
            epubPreferences: ReaderSettings.shared.epubPreferences,
            underlineOpacity: underlineOpacity,
            showHitTestingDebug: showHitTestingDebug,
            swiftUIColorScheme: .light
        )

        return .init(
            lookedUpWords: lookedUpWords,
            bookUniqueWords: Set(lookedUpWords),
            viewConfiguration: configuration,
            clearHighlightTrigger: clearHighlightTrigger,
            removeWordTrigger: nil,
            navigateToLocator: nil,
            isInteractionBlocked: false
        )
    }
}
