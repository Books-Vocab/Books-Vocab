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

    func overflowed(relativeToFullGroup fullGroup: CardLinkGroupPresentation) -> Int {
        max(0, fullGroup.items.count - items.count)
    }
}

struct CardPresentation {
    let word: String
    let translation: String
    let pronunciation: String?
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
    let document: CardDocument

    init(entry: VocabularyEntry, linkOrdering: [String] = Self.defaultLinkOrdering) {
        word = entry.word
        translation = entry.translation
        pronunciation = entry.pronunciation
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

        var normalizedForms: [String] = []
        if let root = entry.rootForm {
            normalizedForms.append(root)
        }
        normalizedForms += entry.inflections.filter { $0 != entry.rootForm }
        forms = normalizedForms

        let grouped = entry.graphLinksByKind
        linkGroups = linkOrdering.compactMap { kind in
            guard let items = grouped[kind], !items.isEmpty else { return nil }
            return CardLinkGroupPresentation(
                id: kind,
                label: items.first?.label ?? kind,
                items: items
            )
        }

        let trimmedContext = sourceContext.trimmingCharacters(in: .whitespacesAndNewlines)
        let computedShowsSourceContext: Bool
        if trimmedContext.isEmpty {
            computedShowsSourceContext = false
        } else {
            computedShowsSourceContext = examples.first != trimmedContext || bookTitle != "Knowledge Graph"
        }

        document = CardDocumentBuilder.build(
            word: word,
            translation: translation,
            pronunciation: pronunciation,
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

    var totalLinkCount: Int {
        linkGroups.reduce(0) { $0 + $1.items.count }
    }

    var showsSourceContext: Bool {
        let trimmedContext = sourceContext.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedContext.isEmpty else { return false }
        return examples.first != trimmedContext || bookTitle != "Knowledge Graph"
    }

    static let defaultLinkOrdering = ["contrasts_with", "confusable", "shares_usage"]
}

extension VocabularyEntry {
    var cardPresentation: CardPresentation {
        CardPresentation(entry: self)
    }

    func linkedEntry(for link: KGCardLinkSummary, in entries: [VocabularyEntry]) -> VocabularyEntry? {
        entries.first { $0.kgCardId == link.cardId }
    }
}
