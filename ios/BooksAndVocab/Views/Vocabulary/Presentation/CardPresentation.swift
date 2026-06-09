import Foundation

struct CardLinkGroupPresentation: Identifiable {
    let id: String
    let label: String
    let items: [KGCardLinkSummary]

    var overflowCount: Int { 0 }

    func limited(to count: Int) -> CardLinkGroupPresentation {
        CardLinkGroupPresentation(
            id: id,
            label: label,
            items: Array(items.prefix(max(0, count)))
        )
    }

    func shuffled() -> CardLinkGroupPresentation {
        CardLinkGroupPresentation(id: id, label: label, items: items.shuffled())
    }

    func overflowed(relativeToFullGroup fullGroup: CardLinkGroupPresentation) -> Int {
        max(0, fullGroup.items.count - items.count)
    }
}

struct CardPresentation {
    let word: String
    let translation: String
    let partOfSpeech: String?
    let difficultyTier: String?
    let reviewMode: VocabularyCardMode
    let examples: [String]
    let sourceContext: String
    let bookTitle: String
    let chapterTitle: String?
    let explanation: String?
    let collocations: [String]
    let forms: [String]
    let syncStatus: Int
    let dateAdded: Date
    let linkGroups: [CardLinkGroupPresentation]
    let activeLinkGroups: [CardLinkGroupPresentation]
    let document: CardDocument

    init(entry: VocabularyEntry, linkOrdering: [String] = Self.defaultLinkOrdering) {
        word = entry.word
        translation = entry.translation
        partOfSpeech = entry.partOfSpeech
        difficultyTier = entry.difficultyTier
        reviewMode = entry.reviewMode
        examples = entry.allReviewExamples
        sourceContext = entry.context
        bookTitle = entry.bookTitle
        chapterTitle = entry.chapterTitle
        explanation = entry.explanation
        collocations = entry.collocations
        syncStatus = entry.syncStatus
        dateAdded = entry.dateAdded

        forms = (entry.rootForm.map { [$0] } ?? []) + entry.inflections.filter { $0 != entry.rootForm }

        let grouped = entry.graphLinksByKind
        linkGroups = linkOrdering.compactMap { kind in
            guard let items = grouped[kind], !items.isEmpty else { return nil }
            return CardLinkGroupPresentation(
                id: kind,
                label: items.first?.label ?? kind,
                items: items
            )
        }

        activeLinkGroups = linkGroups.compactMap { group in
            let activeItems = group.items.filter { !$0.isHidden }
            guard !activeItems.isEmpty else { return nil }
            return CardLinkGroupPresentation(id: group.id, label: group.label, items: activeItems)
        }

        let computedShowsSourceContext = Self.computeShowsSourceContext(
            sourceContext: sourceContext, examples: examples, bookTitle: bookTitle
        )

        document = CardDocumentBuilder.build(
            word: word,
            translation: translation,
            partOfSpeech: partOfSpeech,
            difficultyTier: difficultyTier,
            reviewModeTitle: reviewMode.localizedTitle,
            examples: examples,
            sourceContext: sourceContext,
            bookTitle: bookTitle,
            chapterTitle: chapterTitle,
            explanation: explanation,
            collocations: collocations,
            showsSourceContext: computedShowsSourceContext
        )
    }

    var hiddenLinks: [KGCardLinkSummary] {
        linkGroups.flatMap(\.items).filter(\.isHidden)
    }

    var totalLinkCount: Int {
        activeLinkGroups.reduce(0) { $0 + $1.items.count }
    }

    var showsSourceContext: Bool {
        Self.computeShowsSourceContext(sourceContext: sourceContext, examples: examples, bookTitle: bookTitle)
    }

    /// sourceContext 是否需顯示 — 空白則否；否則僅當它與第一個例句不同、或書名非預設圖譜標題時才顯示。
    /// init 與 showsSourceContext 共用，避免兩處邏輯 drift。
    private static func computeShowsSourceContext(sourceContext: String, examples: [String], bookTitle: String) -> Bool {
        let trimmed = sourceContext.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return false }
        return examples.first != trimmed || bookTitle != "Knowledge Graph"
    }

    static let defaultLinkOrdering = ["contrasts_with", "shares_usage"]
}

extension VocabularyEntry {
    var cardPresentation: CardPresentation {
        CardPresentation(entry: self)
    }

    func linkedEntry(for link: KGCardLinkSummary, in entries: [VocabularyEntry]) -> VocabularyEntry? {
        entries.first { $0.kgCardId == link.cardId }
    }

    func linkedEntry(for link: KGCardLinkSummary, lookup: [String: VocabularyEntry]) -> VocabularyEntry? {
        lookup[link.cardId]
    }

    static func buildCardIdLookup(from entries: [VocabularyEntry]) -> [String: VocabularyEntry] {
        var dict: [String: VocabularyEntry] = [:]
        dict.reserveCapacity(entries.count)
        for entry in entries {
            if let id = entry.kgCardId {
                dict[id] = entry
            }
        }
        return dict
    }
}
