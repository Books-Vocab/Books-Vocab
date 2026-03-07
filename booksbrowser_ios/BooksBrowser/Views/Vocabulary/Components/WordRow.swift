import SwiftUI

struct WordRow: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let word: String
    let translation: String
    let partOfSpeech: String?
    let difficultyTier: String?
    let bookTitle: String?
    let chapterTitle: String?
    let nextReviewAt: Date
    let reviewState: VocabularyReviewState?
    let syncStatus: Int?
    var actionType: String = "add"

    private var isDelete: Bool { actionType == "delete" }
    private var isDue: Bool { nextReviewAt <= Date() }

    var body: some View {
        HStack(alignment: .top, spacing: AppMetrics.spacingMedium) {
            VStack(alignment: .leading, spacing: 6) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    if isDelete {
                        Image(systemName: "trash")
                            .font(.system(size: 12, weight: .thin))
                            .foregroundStyle(vocabSkin.palette.destructive)
                    }

                    Text(word)
                        .font(vocabSkin.typography.rowWord)
                        .strikethrough(isDelete, color: vocabSkin.palette.destructive)
                        .foregroundStyle(isDelete ? vocabSkin.palette.destructive : vocabSkin.palette.primaryText)

                    if let pos = partOfSpeech {
                        Text(pos)
                            .font(.system(size: 14, weight: .medium))
                            .foregroundStyle(vocabSkin.palette.secondaryText)
                    }

                    if isDelete {
                        Spacer()
                        Text("待刪除")
                            .font(vocabSkin.typography.monoLabel)
                            .foregroundStyle(vocabSkin.palette.destructive)
                    }
                }

                if !isDelete {
                    if translation.isEmpty {
                        Label("待翻譯", systemImage: "clock")
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.tertiaryText)
                    } else {
                        Text(translation)
                            .font(vocabSkin.typography.body)
                            .foregroundStyle(vocabSkin.palette.translationText)
                            .lineSpacing(3)
                    }
                }

                if let book = bookTitle, !book.isEmpty {
                    HStack(spacing: 4) {
                        Image(systemName: "book.closed")
                            .font(.system(size: 10, weight: .thin))
                        Text(book)
                            .font(vocabSkin.typography.caption)
                        if let chapter = chapterTitle {
                            Text("· \(chapter)")
                                .font(vocabSkin.typography.caption)
                        }
                    }
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
                }

                if !isDelete {
                    HStack(spacing: 6) {
                        Image(systemName: statusIconName)
                            .font(.system(size: 10, weight: .thin))
                        Text(statusSubtitle)
                            .font(vocabSkin.typography.caption)
                    }
                    .foregroundStyle(statusTone)
                }
            }

            Spacer(minLength: 0)

            if let tier = difficultyTier, !isDelete {
                VStack(alignment: .trailing, spacing: 6) {
                    VocabTierLabel(tier: tier)

                    if let reviewState {
                        reviewStateBadge(reviewState)
                    }
                }
            }
        }
        .padding(.vertical, vocabSkin.spacing.rowPadding)
    }

    private var statusSubtitle: String {
        switch reviewState {
        case .unlearned:
            return "尚未進入複習流程"
        case .due:
            return "現在可複習"
        case .reviewed:
            return "下次 \(nextReviewAt.reviewRelativeDescription())"
        case nil:
            return isDue ? "現在可複習" : "下次 \(nextReviewAt.reviewRelativeDescription())"
        }
    }

    private var statusIconName: String {
        switch reviewState {
        case .unlearned:
            return "sparkles"
        case .due:
            return "clock.badge.exclamationmark"
        case .reviewed:
            return "checkmark.circle"
        case nil:
            return isDue ? "clock.badge.exclamationmark" : "clock.arrow.trianglehead.counterclockwise.rotate.90"
        }
    }

    private var statusTone: Color {
        switch reviewState {
        case .unlearned:
            return vocabSkin.palette.accent
        case .due:
            return vocabSkin.palette.translationText
        case .reviewed:
            return vocabSkin.palette.success
        case nil:
            return isDue ? vocabSkin.palette.translationText : vocabSkin.palette.secondaryText
        }
    }

    private func reviewStateBadge(_ state: VocabularyReviewState) -> some View {
        Text(state.title)
            .font(vocabSkin.typography.captionStrong)
            .padding(.horizontal, 6)
            .padding(.vertical, 4)
            .background(statusTone.opacity(0.08))
            .foregroundStyle(statusTone)
            .clipShape(
                RoundedRectangle(cornerRadius: vocabSkin.radii.tiny, style: .continuous)
            )
    }
}
