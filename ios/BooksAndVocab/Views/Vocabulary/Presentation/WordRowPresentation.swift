import Foundation

extension VocabularyEntry {
    func wordRowViewData(
        showsReviewState: Bool = true,
        showsSourceContext: Bool = true,
        showsDifficultyTier: Bool = true,
        showsReviewProgress: Bool = false,
        showsArchiveStyle: Bool = false,
        now: Date = Date()
    ) -> WordRow.ViewData {
        let isDelete = syncAction == .delete
        let status = rowStatus(showsReviewState: showsReviewState, isDelete: isDelete, now: now)

        let wordTone: WordRow.ViewData.Tone
        let leadingImage: String?
        let leadingToneValue: WordRow.ViewData.Tone?
        let trailingLabelText: String?
        let trailingToneValue: WordRow.ViewData.Tone?

        if isDelete {
            wordTone = .destructive
            leadingImage = "trash"
            leadingToneValue = .destructive
            trailingLabelText = "待刪除"
            trailingToneValue = .destructive
        } else if showsArchiveStyle {
            wordTone = .secondary
            leadingImage = "archivebox"
            leadingToneValue = .tertiary
            trailingLabelText = nil
            trailingToneValue = nil
        } else {
            wordTone = .primary
            leadingImage = nil
            leadingToneValue = nil
            trailingLabelText = nil
            trailingToneValue = nil
        }

        return WordRow.ViewData(
            id: id,
            word: word,
            wordTone: wordTone,
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
            leadingSystemImage: leadingImage,
            leadingTone: leadingToneValue,
            trailingLabel: trailingLabelText,
            trailingTone: trailingToneValue,
            statusText: status?.text,
            statusTone: status?.tone
        )
    }

    private func rowStatus(
        showsReviewState: Bool,
        isDelete: Bool,
        now: Date
    ) -> (text: String, tone: WordRow.ViewData.Tone)? {
        guard showsReviewState, !isDelete else { return nil }

        switch reviewState(at: now) {
        case .unlearned:
            return (L10n.string("未複習"), .tertiary)
        case .due:
            return (L10n.string("待複習"), .reviewDue)
        case .reviewed:
            return (L10n.format("下次 %@", nextReviewAt.reviewRelativeDescription(now: now)), .secondary)
        }
    }

    private func reviewProgressData(
        showsReviewProgress: Bool,
        isDelete: Bool,
        now: Date
    ) -> VocabReviewProgress? {
        guard showsReviewProgress, !isDelete else { return nil }

        switch reviewState(at: now) {
        case .unlearned:
            return .init(
                statusLabel: reviewProgressStatusLabel(now: now),
                detailLabel: L10n.format("首輪 %@", reviewIntervalHours.compactHourLabel),
                ratio: nil
            )
        case .due, .reviewed:
            let interval = max(nextReviewAt.timeIntervalSince(reviewProgressStartDate), 60)
            let elapsed = max(0, now.timeIntervalSince(reviewProgressStartDate))
            let ratio = max(elapsed / interval, 0)

            return .init(
                statusLabel: reviewProgressStatusLabel(now: now),
                detailLabel: "\(elapsed.compactReviewLabel) / \(interval.compactReviewLabel)",
                ratio: ratio
            )
        }
    }

    private func reviewProgressStatusLabel(now: Date) -> String {
        switch reviewState(at: now) {
        case .unlearned:
            return L10n.string("未學習")
        case .due:
            return L10n.string("待複習")
        case .reviewed:
            return L10n.string("已複習")
        }
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

// 緊湊時間標籤格式化見 CompactTimeFormatting.swift（與 WordDetailPresentation 共用）。
