import Foundation

enum VocabularyRoleFilter: String, CaseIterable, Identifiable {
    case all
    case learning
    case dictionary

    var id: String { rawValue }

    var title: String {
        switch self {
        case .all: L10n.string("dictionary.filter.all")
        case .learning: L10n.string("dictionary.filter.learning")
        case .dictionary: L10n.string("dictionary.filter.dictionary")
        }
    }
}

enum VocabularyEntryPresentation {
    static func pendingEntries(in entries: [VocabularyEntry]) -> [VocabularyEntry] {
        entries.filter(\.shouldUploadOnNextSync)
    }

    static func filterByRole(
        _ entries: [VocabularyEntry], filter: VocabularyRoleFilter
    ) -> [VocabularyEntry] {
        switch filter {
        case .all: entries
        case .learning: entries.filter { $0.cardRole == .learning }
        case .dictionary: entries.filter { $0.cardRole == .dictionary }
        }
    }

    /// 多選模式下實際可被選取的 row id。
    ///
    /// 字典卡不參與批次刪除 / 封存，所以「全選」只挑得動 learning row。**同一份
    /// 集合必須同時餵給 `selectAll` 與 `updateVisibleCount`** —— 兩邊各自算一次
    /// 就會分岔：在「全部」tab 上只要畫面有任何一張字典卡，`isAllSelected`
    /// （`selectedIDs.count == visibleCount`）永遠不成立，toolbar 只會一直提供
    /// 「全選」，使用者按不到「取消全選」。
    static func selectableIDs(in entries: [VocabularyEntry]) -> [UUID] {
        entries.filter { $0.cardRole == .learning }.map(\.id)
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
