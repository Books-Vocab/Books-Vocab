import Foundation

extension VocabularyEntry {
    func wordRowViewData(
        showsReviewState: Bool = true,
        showsSourceContext: Bool = true,
        showsDifficultyTier: Bool = true,
        showsReviewProgress: Bool = false,
        now: Date = Date()
    ) -> WordRow.ViewData {
        let isDelete = syncAction == .delete
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
            difficultyTier: showsDifficultyTier ? difficultyTier.nilIfBlank : nil,
            reviewProgress: reviewProgressData(
                showsReviewProgress: showsReviewProgress,
                isDelete: isDelete,
                now: now
            ),
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
            return (L10n.string("未複習"), .tertiary)
        case .due:
            return (L10n.string("待複習"), .reviewDue)
        case .reviewed:
            return (L10n.format("下次 %@", nextReviewAt.reviewRelativeDescription()), .secondary)
        }
    }

    private func reviewProgressData(
        showsReviewProgress: Bool,
        isDelete: Bool,
        now: Date
    ) -> VocabReviewProgress? {
        guard showsReviewProgress, !isDelete else { return nil }

        switch reviewState {
        case .unlearned:
            return .init(
                statusLabel: reviewProgressStatusLabel,
                detailLabel: L10n.format("首輪 %@", reviewIntervalHours.compactHourLabel),
                fraction: nil,
                tone: .yellow
            )
        case .due, .reviewed:
            let interval = max(nextReviewAt.timeIntervalSince(reviewProgressStartDate), 60)
            let elapsed = max(0, now.timeIntervalSince(reviewProgressStartDate))
            let fraction = min(max(elapsed / interval, 0), 1)

            return .init(
                statusLabel: reviewProgressStatusLabel,
                detailLabel: "\(elapsed.compactReviewProgressLabel) / \(interval.compactReviewProgressLabel)",
                fraction: fraction,
                tone: reviewProgressTone(for: fraction)
            )
        }
    }

    private var reviewProgressStatusLabel: String {
        switch reviewState {
        case .unlearned:
            return L10n.string("未學習")
        case .due:
            return L10n.string("待複習")
        case .reviewed:
            return L10n.string("已複習")
        }
    }

    private func reviewProgressTone(for fraction: Double) -> VocabReviewProgress.Tone {
        if fraction >= 1 {
            return .red
        }
        if fraction >= 0.72 {
            return .orange
        }
        if fraction >= 0.4 {
            return .yellow
        }
        return .green
    }

    private var reviewProgressStartDate: Date {
        lastReviewedAt ?? dateAdded
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

private extension TimeInterval {
    var compactReviewProgressLabel: String {
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
            return hours < 10 ? hours.singleDecimalString + "h" : "\(Int(hours.rounded()))h"
        }

        let days = seconds / day
        return days < 10 ? days.singleDecimalString + "d" : "\(Int(days.rounded()))d"
    }
}

private extension Double {
    var compactHourLabel: String {
        (self * 3600).compactReviewProgressLabel
    }
}

private extension Double {
    var singleDecimalString: String {
        let rounded = (self * 10).rounded() / 10
        if rounded == rounded.rounded() {
            return String(Int(rounded))
        }
        return String(format: "%.1f", rounded)
    }
}
