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
    var showsReviewState: Bool = true

    private var isDelete: Bool { actionType == "delete" }
    private var isDue: Bool { nextReviewAt <= Date() }

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            VStack(alignment: .leading, spacing: 4) {
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
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.tertiaryText)
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
                            .foregroundStyle(vocabSkin.palette.secondaryText)
                            .lineLimit(2)
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

                if !isDelete && showsReviewState {
                    Text(statusSubtitle)
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(statusTone)
                        .lineLimit(1)
                }
            }

            Spacer(minLength: 0)

            if let tier = difficultyTier, !isDelete {
                VStack(alignment: .trailing, spacing: 4) {
                    VocabTierLabel(tier: tier)
                }
            }
        }
        .padding(.vertical, 7)
    }

    private var statusSubtitle: String {
        switch reviewState {
        case .unlearned:
            return "未複習"
        case .due:
            return "待複習"
        case .reviewed:
            return "下次 \(nextReviewAt.reviewRelativeDescription())"
        case nil:
            return isDue ? "待複習" : "下次 \(nextReviewAt.reviewRelativeDescription())"
        }
    }

    private var statusTone: Color {
        switch reviewState {
        case .unlearned:
            return vocabSkin.palette.tertiaryText
        case .due:
            return vocabSkin.tierColor(for: "intermediate")
        case .reviewed:
            return vocabSkin.palette.secondaryText
        case nil:
            return isDue ? vocabSkin.tierColor(for: "intermediate") : vocabSkin.palette.tertiaryText
        }
    }
}
