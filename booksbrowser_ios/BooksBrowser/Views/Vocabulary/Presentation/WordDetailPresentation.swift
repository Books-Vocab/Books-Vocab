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
                text: "\(card.totalLinkCount) connections"
            ),
            syncMetadataItem(for: card.syncStatus)
        ]
    }

    private static func syncMetadataItem(
        for syncStatus: Int
    ) -> WordDetailPresenter.State.MetadataItem {
        switch syncStatus {
        case 1:
            return .init(icon: "checkmark.circle", text: "已同步")
        case 2:
            return .init(icon: "exclamationmark.circle", text: "同步失敗")
        default:
            return .init(icon: "clock", text: "待同步")
        }
    }
}
