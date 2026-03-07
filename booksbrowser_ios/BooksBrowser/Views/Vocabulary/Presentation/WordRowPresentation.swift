import Foundation

extension VocabularyEntry {
    func wordRowViewData(
        showsReviewState: Bool = true,
        showsSourceContext: Bool = true
    ) -> WordRow.ViewData {
        let isDelete = actionType == "delete"
        let status = rowStatus(showsReviewState: showsReviewState, isDelete: isDelete)

        return WordRow.ViewData(
            id: id,
            word: word,
            wordTone: isDelete ? .destructive : .primary,
            isStrikethrough: isDelete,
            partOfSpeech: partOfSpeech,
            translation: translation.nilIfBlank,
            bookTitle: showsSourceContext ? bookTitle.nilIfBlank : nil,
            chapterTitle: showsSourceContext ? chapterTitle.nilIfBlank : nil,
            difficultyTier: difficultyTier.nilIfBlank,
            leadingSystemImage: isDelete ? "trash" : nil,
            leadingTone: isDelete ? .destructive : nil,
            trailingLabel: isDelete ? "待刪除" : nil,
            trailingTone: isDelete ? .destructive : nil,
            statusText: status?.text,
            statusTone: status?.tone
        )
    }

    private func rowStatus(
        showsReviewState: Bool,
        isDelete: Bool
    ) -> (text: String, tone: WordRow.ViewData.Tone)? {
        guard showsReviewState, !isDelete else { return nil }

        switch reviewState {
        case .unlearned:
            return ("未複習", .tertiary)
        case .due:
            return ("待複習", .reviewDue)
        case .reviewed:
            return ("下次 \(nextReviewAt.reviewRelativeDescription())", .secondary)
        }
    }
}

private extension String {
    var nilIfBlank: String? {
        let trimmed = trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}

private extension Optional where Wrapped == String {
    var nilIfBlank: String? {
        self?.nilIfBlank
    }
}
