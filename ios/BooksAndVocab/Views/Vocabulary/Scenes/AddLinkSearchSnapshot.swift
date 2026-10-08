import Foundation

/// Everything the Add Link sheet derives from one search query, computed once
/// per render instead of once per reader (lookup marker, list, row selection).
struct AddLinkSearchSnapshot {
    /// The query with surrounding whitespace removed.
    let trimmedQuery: String
    let candidates: [VocabularyEntry]
    /// Exact-word state of the query (missing / already linked / archived…),
    /// nil for an empty query. Computed even while partial matches are listed:
    /// the "create" entry must stay reachable next to them (`run` beside `running`).
    let exactTargetState: AddLinkLocalTargetState?

    var isEmptyQuery: Bool { trimmedQuery.isEmpty }

    func containsCandidate(_ entry: VocabularyEntry) -> Bool {
        candidates.contains { $0.id == entry.id }
    }

    static func make(
        query: String,
        sourceEntry: VocabularyEntry,
        allEntries: [VocabularyEntry]
    ) -> AddLinkSearchSnapshot {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        let candidates = AddLinkCoordinator.localCandidates(
            query: query,
            sourceEntry: sourceEntry,
            allEntries: allEntries
        )
        let exactTargetState: AddLinkLocalTargetState? = trimmed.isEmpty
            ? nil
            : AddLinkCreationCoordinator.localTargetState(
                query: query,
                sourceEntry: sourceEntry,
                allEntries: allEntries
            )
        return AddLinkSearchSnapshot(
            trimmedQuery: trimmed,
            candidates: candidates,
            exactTargetState: exactTargetState
        )
    }
}
