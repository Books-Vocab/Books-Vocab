import Foundation

enum WordDetailPresentation {
    static func state(
        for entry: VocabularyEntry,
        in allEntries: [VocabularyEntry]
    ) -> WordDetailPresenter.State {
        let card = entry.cardPresentation

        return WordDetailPresenter.State(
            title: card.word,
            systemImage: "book.closed",
            card: card,
            rootForm: entry.rootForm,
            metadataItems: metadataItems(for: card),
            navigableLinkCardIDs: Set(
                card.linkGroups
                    .flatMap(\.items)
                    .compactMap { link in
                        entry.linkedEntry(for: link, in: allEntries) == nil ? nil : link.cardId
                    }
            ),
            reviewInfo: entry.shouldAppearInKnowledgeList ? reviewInfo(for: entry) : nil
        )
    }

    private static func metadataItems(
        for card: CardPresentation
    ) -> [WordDetailPresenter.State.MetadataItem] {
        [
            .init(
                icon: "calendar",
                text: card.dateAdded.formatted(date: .abbreviated, time: .omitted)
            ),
            .init(
                icon: "link",
                text: L10n.format("%@ 個連結", "\(card.totalLinkCount)")
            ),
            syncMetadataItem(for: card.syncStatus)
        ]
    }

    private static func reviewInfo(
        for entry: VocabularyEntry
    ) -> WordDetailPresenter.State.ReviewInfo {
        let state = entry.reviewState
        let snapshot = entry.reviewSnapshot

        let stateTone: VocabActionTone
        switch state {
        case .unlearned:
            stateTone = .neutral
        case .due:
            stateTone = .warning
        case .reviewed:
            stateTone = .success
        }

        let nextReviewLabel: String?
        if state == .unlearned {
            nextReviewLabel = nil
        } else {
            nextReviewLabel = L10n.format("下次 %@", snapshot.nextReviewAt.reviewRelativeDescription())
        }

        let intervalLabel: String?
        if snapshot.intervalHours < 24 {
            intervalLabel = L10n.format("間隔 %@h", String(format: "%.0f", snapshot.intervalHours))
        } else {
            let days = snapshot.intervalHours / 24
            intervalLabel = L10n.format("間隔 %@天", String(format: "%.1f", days))
        }

        let reviewCountLabel: String? = snapshot.reviewCount > 0
            ? L10n.format("已複習 %@ 次", "\(snapshot.reviewCount)")
            : nil

        let streakLabel: String? = snapshot.streak > 1
            ? L10n.format("連續 %@ 次", "\(snapshot.streak)")
            : nil

        return WordDetailPresenter.State.ReviewInfo(
            stateLabel: state.title,
            stateTone: stateTone,
            nextReviewLabel: nextReviewLabel,
            intervalLabel: intervalLabel,
            reviewCountLabel: reviewCountLabel,
            streakLabel: streakLabel
        )
    }

    private static func syncMetadataItem(
        for syncStatus: Int
    ) -> WordDetailPresenter.State.MetadataItem {
        switch VocabularySyncState(rawValue: syncStatus) ?? .pending {
        case .synced:
            return .init(icon: "checkmark.circle", text: L10n.string("已同步"))
        case .failed:
            return .init(icon: "exclamationmark.circle", text: L10n.string("同步失敗"))
        case .pending:
            return .init(icon: "clock", text: L10n.string("待同步"))
        }
    }
}
