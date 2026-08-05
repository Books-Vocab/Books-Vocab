import Foundation

enum VocabularyEntryPresentation {
    static func pendingEntries(in entries: [VocabularyEntry]) -> [VocabularyEntry] {
        entries.filter(\.shouldUploadOnNextSync)
    }

    /// Single-pass partition of knowledge entries into review-state buckets.
    /// Returns counts and the filtered+sorted list for the selected state.
    struct ClassifiedResult {
        var dueBucket: [VocabularyEntry]
        var unlearnedBucket: [VocabularyEntry]
        var reviewedBucket: [VocabularyEntry]

        var dueCount: Int { dueBucket.count }
        var unlearnedCount: Int { unlearnedBucket.count }
        var reviewedCount: Int { reviewedBucket.count }

        func count(for state: VocabularyReviewState) -> Int {
            switch state {
            case .due: return dueCount
            case .unlearned: return unlearnedCount
            case .reviewed: return reviewedCount
            }
        }

        func bucket(for state: VocabularyReviewState) -> [VocabularyEntry] {
            switch state {
            case .due: return dueBucket
            case .unlearned: return unlearnedBucket
            case .reviewed: return reviewedBucket
            }
        }

        func mergedBucket(for states: Set<VocabularyReviewState>) -> [VocabularyEntry] {
            if states.isEmpty {
                return dueBucket + unlearnedBucket + reviewedBucket
            }
            var result: [VocabularyEntry] = []
            for state in VocabularyReviewState.allCases where states.contains(state) {
                result.append(contentsOf: bucket(for: state))
            }
            return result
        }
    }

    static func classifyKnowledgeEntries(
        in entries: [VocabularyEntry],
        now: Date
    ) -> ClassifiedResult {
        var due: [VocabularyEntry] = []
        var unlearned: [VocabularyEntry] = []
        var reviewed: [VocabularyEntry] = []

        for entry in entries {
            guard entry.shouldAppearInReview else { continue }
            switch entry.reviewState(at: now) {
            case .due: due.append(entry)
            case .unlearned: unlearned.append(entry)
            case .reviewed: reviewed.append(entry)
            }
        }

        return ClassifiedResult(
            dueBucket: due,
            unlearnedBucket: unlearned,
            reviewedBucket: reviewed
        )
    }

    static func sortAndFilter(
        _ entries: [VocabularyEntry],
        searchText: String,
        sortOption: KGVocabSortOption = .default,
        now: Date
    ) -> [VocabularyEntry] {
        // Filter first to reduce sort input size
        let base = searchText.isEmpty ? entries : entries.filter {
            $0.word.localizedCaseInsensitiveContains(searchText) ||
            $0.translation.localizedCaseInsensitiveContains(searchText)
        }

        switch sortOption {
        case .default:
            return base.sorted { compareKnowledgeEntries($0, $1, now: now) }
        case .alphabetical:
            return base.sorted {
                $0.word.localizedCaseInsensitiveCompare($1.word) == .orderedAscending
            }
        case .dateAdded:
            return base.sorted { $0.effectiveDateAdded > $1.effectiveDateAdded }
        case .difficulty:
            return base.sorted { lhs, rhs in
                if lhs.reviewEligible != rhs.reviewEligible {
                    return lhs.reviewEligible
                }
                let lhsTier = tierPriority(lhs.difficultyTier)
                let rhsTier = tierPriority(rhs.difficultyTier)
                if lhsTier != rhsTier { return lhsTier < rhsTier }
                return lhs.word.localizedCaseInsensitiveCompare(rhs.word) == .orderedAscending
            }
        }
    }

    static func archivedEntries(in entries: [VocabularyEntry]) -> [VocabularyEntry] {
        entries
            .filter(\.shouldAppearInArchiveList)
            .sorted { $0.word.localizedCaseInsensitiveCompare($1.word) == .orderedAscending }
    }

    static func filteredArchivedEntries(
        in entries: [VocabularyEntry],
        searchText: String
    ) -> [VocabularyEntry] {
        let all = archivedEntries(in: entries)
        guard !searchText.isEmpty else { return all }
        return all.filter {
            $0.word.localizedCaseInsensitiveContains(searchText) ||
            $0.translation.localizedCaseInsensitiveContains(searchText)
        }
    }

    static func compareKnowledgeEntries(_ lhs: VocabularyEntry, _ rhs: VocabularyEntry, now: Date) -> Bool {
        if lhs.reviewEligible != rhs.reviewEligible {
            return lhs.reviewEligible
        }
        if !lhs.reviewEligible {
            if lhs.effectiveDateAdded != rhs.effectiveDateAdded {
                return lhs.effectiveDateAdded > rhs.effectiveDateAdded
            }
            return lhs.word.localizedCaseInsensitiveCompare(rhs.word) == .orderedAscending
        }
        if reviewPriority(lhs.reviewState(at: now)) != reviewPriority(rhs.reviewState(at: now)) {
            return reviewPriority(lhs.reviewState(at: now)) < reviewPriority(rhs.reviewState(at: now))
        }
        if lhs.nextReviewAt != rhs.nextReviewAt {
            return lhs.nextReviewAt < rhs.nextReviewAt
        }
        let lhsTier = tierPriority(lhs.difficultyTier)
        let rhsTier = tierPriority(rhs.difficultyTier)
        if lhsTier != rhsTier {
            return lhsTier < rhsTier
        }
        return lhs.word.localizedCaseInsensitiveCompare(rhs.word) == .orderedAscending
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
