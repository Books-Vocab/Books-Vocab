import Foundation

enum VocabularyEntryPresentation {
    static func pendingEntries(in entries: [VocabularyEntry]) -> [VocabularyEntry] {
        entries.filter { !$0.isSynced }
    }

    static func syncedKnowledgeEntries(in entries: [VocabularyEntry]) -> [VocabularyEntry] {
        entries
            .filter { $0.syncState == .synced && $0.syncAction != .delete }
            .sorted(by: compareKnowledgeEntries)
    }

    static func filteredPendingEntries(
        in entries: [VocabularyEntry],
        searchText: String
    ) -> [VocabularyEntry] {
        let sortedPending = pendingEntries(in: entries).sorted(by: comparePendingEntries)

        guard !searchText.isEmpty else { return sortedPending }
        return sortedPending.filter {
            $0.word.localizedCaseInsensitiveContains(searchText) ||
            $0.translation.localizedCaseInsensitiveContains(searchText)
        }
    }

    static func filteredKnowledgeEntries(
        in entries: [VocabularyEntry],
        reviewState: VocabularyReviewState,
        searchText: String
    ) -> [VocabularyEntry] {
        let stateFiltered = syncedKnowledgeEntries(in: entries).filter { $0.reviewState == reviewState }
        guard !searchText.isEmpty else { return stateFiltered }
        return stateFiltered.filter {
            $0.word.localizedCaseInsensitiveContains(searchText) ||
            $0.translation.localizedCaseInsensitiveContains(searchText)
        }
    }

    static func knowledgeReviewEntries(in entries: [VocabularyEntry]) -> [VocabularyEntry] {
        syncedKnowledgeEntries(in: entries).filter {
            $0.reviewState == .due || $0.reviewState == .unlearned
        }
    }

    static func countKnowledgeEntries(
        in entries: [VocabularyEntry],
        reviewState: VocabularyReviewState
    ) -> Int {
        syncedKnowledgeEntries(in: entries).filter { $0.reviewState == reviewState }.count
    }

    static func compareKnowledgeEntries(_ lhs: VocabularyEntry, _ rhs: VocabularyEntry) -> Bool {
        if reviewPriority(lhs.reviewState) != reviewPriority(rhs.reviewState) {
            return reviewPriority(lhs.reviewState) < reviewPriority(rhs.reviewState)
        }
        if lhs.reviewState != .reviewed && lhs.nextReviewAt != rhs.nextReviewAt {
            return lhs.nextReviewAt < rhs.nextReviewAt
        }
        let lhsTier = tierPriority(lhs.difficultyTier)
        let rhsTier = tierPriority(rhs.difficultyTier)
        if lhsTier != rhsTier {
            return lhsTier < rhsTier
        }
        return lhs.word.localizedCaseInsensitiveCompare(rhs.word) == .orderedAscending
    }

    static func comparePendingEntries(_ lhs: VocabularyEntry, _ rhs: VocabularyEntry) -> Bool {
        if lhs.isReviewDue != rhs.isReviewDue {
            return lhs.isReviewDue && !rhs.isReviewDue
        }
        if lhs.nextReviewAt != rhs.nextReviewAt {
            return lhs.nextReviewAt < rhs.nextReviewAt
        }
        return lhs.dateAdded > rhs.dateAdded
    }

    private static func reviewPriority(_ state: VocabularyReviewState) -> Int {
        switch state {
        case .due: return 0
        case .unlearned: return 1
        case .reviewed: return 2
        }
    }

    private static func tierPriority(_ tier: String?) -> Int {
        switch tier {
        case "core": return 0
        case "intermediate": return 1
        case "advanced": return 2
        case "rare": return 3
        default: return 4
        }
    }
}
