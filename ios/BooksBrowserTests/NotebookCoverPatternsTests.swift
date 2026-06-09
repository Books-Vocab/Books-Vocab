//
//  NotebookCoverPatternsTests.swift
//  Books & Vocab Tests
//
//  Pins the `NotebookCoverPattern` enum's public surface. Raw values are
//  persisted to `coverPattern: String?` on notebook / podcast-series rows
//  and round-tripped via `NotebookCoverPattern(rawValue:)` at every render
//  callsite (BookshelfView, PodcastEpisodeListView, NotebookEditSheet,
//  NotebookCard). Renaming a case would silently drop existing covers, and
//  removing one would break `allCases`-driven picker rows.
//

import Foundation
import Testing
@testable import BooksBrowser

struct NotebookCoverPatternsTests {

    // MARK: - allCases completeness + ordering

    @Test func allCasesContainsAllSixPatterns() async throws {
        #expect(NotebookCoverPattern.allCases.count == 6)
    }

    @Test func allCasesOrderingIsStable() async throws {
        // Order drives the NotebookEditSheet picker row layout — lock it.
        #expect(
            NotebookCoverPattern.allCases.map(\.rawValue)
            == ["dots", "lines", "grid", "waves", "circles", "noise"]
        )
    }

    // MARK: - rawValue round-trip (persistence contract)

    @Test func rawValueRoundTripsForEveryCase() async throws {
        for pattern in NotebookCoverPattern.allCases {
            let restored = NotebookCoverPattern(rawValue: pattern.rawValue)
            #expect(restored == pattern)
        }
    }

    @Test func rawValueIsStableLowercaseIdentifier() async throws {
        // Schema stability: raw values are ASCII lowercase. Any future case must
        // follow the same convention to keep CSV / DB columns predictable.
        for pattern in NotebookCoverPattern.allCases {
            #expect(pattern.rawValue == pattern.rawValue.lowercased())
            #expect(pattern.rawValue.allSatisfy { $0.isASCII })
            #expect(!pattern.rawValue.isEmpty)
        }
    }

    @Test func unknownRawValueReturnsNil() async throws {
        #expect(NotebookCoverPattern(rawValue: "") == nil)
        #expect(NotebookCoverPattern(rawValue: "DOTS") == nil)         // case-sensitive
        #expect(NotebookCoverPattern(rawValue: "rainbow") == nil)
    }

    // MARK: - Identifiable conformance

    @Test func idMatchesRawValueForEveryCase() async throws {
        for pattern in NotebookCoverPattern.allCases {
            #expect(pattern.id == pattern.rawValue)
        }
    }

    @Test func idsAreUniqueAcrossAllCases() async throws {
        let ids = NotebookCoverPattern.allCases.map(\.id)
        #expect(Set(ids).count == ids.count)
    }

    // MARK: - label() — user-facing picker text

    @Test func labelIsNonEmptyForEveryCase() async throws {
        for pattern in NotebookCoverPattern.allCases {
            #expect(!pattern.label.isEmpty)
        }
    }

    @Test func labelsAreUniqueAcrossAllCases() async throws {
        let labels = NotebookCoverPattern.allCases.map(\.label)
        #expect(Set(labels).count == labels.count)
    }

    @Test func labelExactValuesArePinned() async throws {
        // Lock the zh-Hant label mapping — these strings ship in NotebookEditSheet
        // picker rows. Any rename here is a UX change requiring a deliberate update.
        #expect(NotebookCoverPattern.dots.label == "圓點")
        #expect(NotebookCoverPattern.lines.label == "條紋")
        #expect(NotebookCoverPattern.grid.label == "格線")
        #expect(NotebookCoverPattern.waves.label == "波浪")
        #expect(NotebookCoverPattern.circles.label == "同心圓")
        #expect(NotebookCoverPattern.noise.label == "噪點")
    }
}
