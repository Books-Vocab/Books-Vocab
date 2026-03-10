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
            reviewProgress: entry.shouldAppearInKnowledgeList ? reviewProgress(for: entry) : nil
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

    private static func reviewProgress(
        for entry: VocabularyEntry,
        now: Date = Date()
    ) -> VocabReviewProgress {
        let state = entry.reviewState

        switch state {
        case .unlearned:
            return VocabReviewProgress(
                statusLabel: L10n.string("未學習"),
                detailLabel: L10n.format("首輪 %@", entry.reviewIntervalHours.detailCompactHourLabel),
                fraction: nil,
                tone: .yellow
            )
        case .due, .reviewed:
            let startDate = entry.lastReviewedAt ?? entry.dateAdded
            let interval = max(entry.nextReviewAt.timeIntervalSince(startDate), 60)
            let elapsed = max(0, now.timeIntervalSince(startDate))
            let fraction = min(max(elapsed / interval, 0), 1)

            let detailLabel = "\(elapsed.detailCompactLabel) / \(interval.detailCompactLabel)"

            let tone: VocabReviewProgress.Tone
            if fraction >= 1 { tone = .red }
            else if fraction >= 0.72 { tone = .orange }
            else if fraction >= 0.4 { tone = .yellow }
            else { tone = .green }

            return VocabReviewProgress(
                statusLabel: state == .due ? L10n.string("待複習") : L10n.string("已複習"),
                detailLabel: detailLabel,
                fraction: fraction,
                tone: tone
            )
        }
    }

    // MARK: - Sync metadata

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

// MARK: - Compact time formatting (mirrors WordRowPresentation helpers)

private extension TimeInterval {
    var detailCompactLabel: String {
        let seconds = max(0, self)
        let minute: TimeInterval = 60
        let hour: TimeInterval = 3600
        let day: TimeInterval = 86_400

        if seconds < hour {
            let minutes = max(1, Int((seconds / minute).rounded()))
            return "\(minutes)m"
        }
        if seconds < day {
            let hours = seconds / hour
            return hours < 10 ? hours.detailSingleDecimal + "h" : "\(Int(hours.rounded()))h"
        }
        let days = seconds / day
        return days < 10 ? days.detailSingleDecimal + "d" : "\(Int(days.rounded()))d"
    }
}

private extension Double {
    var detailCompactHourLabel: String {
        (self * 3600).detailCompactLabel
    }

    var detailSingleDecimal: String {
        let rounded = (self * 10).rounded() / 10
        if rounded == rounded.rounded() {
            return String(Int(rounded))
        }
        return String(format: "%.1f", rounded)
    }
}
