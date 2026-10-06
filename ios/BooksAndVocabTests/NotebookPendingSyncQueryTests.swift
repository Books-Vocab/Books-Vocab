#if os(iOS)

import Foundation
import Testing

struct NotebookPendingSyncQueryTests {
    @Test
    func notebookListPendingQueryIncludesPendingDeleteIntents() throws {
        let sourceURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()  // BooksAndVocabTests
            .deletingLastPathComponent()  // ios
            .appendingPathComponent(
                "BooksAndVocab/Views/Vocabulary/Scenes/NotebookListView.swift"
            )
        let source = try String(contentsOf: sourceURL, encoding: .utf8)
        let initializerStart = try #require(source.range(of: "init(detailState: DetailRouter)"))
        let initializerEnd = try #require(
            source.range(of: "    }", range: initializerStart.upperBound..<source.endIndex)
        )
        let initializer = source[initializerStart.lowerBound..<initializerEnd.lowerBound]

        // The notebook home drives its only SyncPendingTip from this query. It
        // must match SyncView's syncStatus != 1 contract, including pending+delete.
        let expectedPendingQuery =
            "_pendingEntries = Query(filter: #Predicate<VocabularyEntry> { $0.syncStatus != 1 })"
        #expect(
            initializer.contains(expectedPendingQuery),
            "NotebookListContent pending query must include pending delete intents"
        )
    }
}

#endif
