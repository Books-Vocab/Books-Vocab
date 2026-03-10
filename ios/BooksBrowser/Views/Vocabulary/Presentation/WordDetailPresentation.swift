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
            )
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
