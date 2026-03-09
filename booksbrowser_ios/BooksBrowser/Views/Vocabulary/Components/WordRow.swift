import SwiftUI

struct WordRow: View {
    struct ViewData: Identifiable, Hashable {
        struct ReviewProgress: Hashable {
            enum Tone: Hashable {
                case green
                case yellow
                case orange
                case red
            }

            let statusLabel: String
            let elapsedLabel: String
            let totalLabel: String
            let fraction: Double
            let tone: Tone
        }

        enum Tone: Hashable {
            case primary
            case secondary
            case tertiary
            case quaternary
            case destructive
            case reviewDue
        }

        let id: UUID
        let word: String
        let wordTone: Tone
        let isStrikethrough: Bool
        let partOfSpeech: String?
        let translation: String?
        let bookTitle: String?
        let chapterTitle: String?
        let difficultyTier: String?
        let reviewProgress: ReviewProgress?
        let leadingSystemImage: String?
        let leadingTone: Tone?
        let trailingLabel: String?
        let trailingTone: Tone?
        let statusText: String?
        let statusTone: Tone?
    }

    @Environment(\.vocabSkin) private var vocabSkin
    let viewData: ViewData

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    if let systemImage = viewData.leadingSystemImage {
                        Image(systemName: systemImage)
                            .font(vocabSkin.typography.iconSmall)
                            .foregroundStyle(resolveTone(viewData.leadingTone ?? .tertiary))
                    }

                    Text(viewData.word)
                        .font(vocabSkin.typography.rowWord)
                        .strikethrough(viewData.isStrikethrough, color: resolveTone(viewData.wordTone))
                        .foregroundStyle(resolveTone(viewData.wordTone))

                    if let pos = viewData.partOfSpeech {
                        Text(pos)
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.tertiaryText)
                    }

                    if let trailingLabel = viewData.trailingLabel {
                        Spacer()
                        Text(trailingLabel.localized)
                            .font(vocabSkin.typography.monoLabel)
                            .foregroundStyle(resolveTone(viewData.trailingTone ?? .tertiary))
                    }
                }

                if let translation = viewData.translation, !translation.isEmpty {
                    Text(translation)
                        .font(vocabSkin.typography.body)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                        .lineLimit(2)
                } else if !viewData.isStrikethrough {
                    Label("待翻譯", systemImage: "clock")
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.tertiaryText)
                }

                if let reviewProgress = viewData.reviewProgress, !viewData.isStrikethrough {
                    reviewProgressView(reviewProgress)
                }

                if let book = viewData.bookTitle, !book.isEmpty {
                    HStack(spacing: 4) {
                        Image(systemName: "book.closed")
                            .font(vocabSkin.typography.iconTiny)
                        Text(book)
                            .font(vocabSkin.typography.caption)
                        if let chapter = viewData.chapterTitle {
                            Text("· \(chapter)")
                                .font(vocabSkin.typography.caption)
                        }
                    }
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
                }

                if let statusText = viewData.statusText, !statusText.isEmpty {
                    Text(statusText.localized)
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(resolveTone(viewData.statusTone ?? .tertiary))
                        .lineLimit(1)
                }
            }

            Spacer(minLength: 0)

            if let tier = viewData.difficultyTier, viewData.reviewProgress == nil, !viewData.isStrikethrough {
                VStack(alignment: .trailing, spacing: 4) {
                    VocabTierLabel(tier: tier)
                }
            }
        }
        .padding(.vertical, 7)
    }

    private func reviewProgressView(_ progress: ViewData.ReviewProgress) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .center, spacing: 8) {
                Text(progress.statusLabel.localized)
                    .font(vocabSkin.typography.captionStrong)
                    .foregroundStyle(resolveProgressTone(progress.tone))

                Spacer(minLength: 8)

                Text("\(progress.elapsedLabel) / \(progress.totalLabel)")
                    .font(vocabSkin.typography.monoLabel)
                    .foregroundStyle(vocabSkin.palette.secondaryText)
            }

            GeometryReader { proxy in
                ZStack(alignment: .leading) {
                    Capsule(style: .continuous)
                        .fill(vocabSkin.palette.mutedFill.opacity(1.25))

                    Capsule(style: .continuous)
                        .fill(resolveProgressTone(progress.tone))
                        .frame(width: max(6, proxy.size.width * progress.fraction))
                }
            }
            .frame(height: 5)
        }
        .padding(.top, 2)
    }

    private func resolveTone(_ tone: ViewData.Tone) -> Color {
        switch tone {
        case .primary:
            return vocabSkin.palette.primaryText
        case .secondary:
            return vocabSkin.palette.secondaryText
        case .tertiary:
            return vocabSkin.palette.tertiaryText
        case .quaternary:
            return vocabSkin.palette.quaternaryText
        case .destructive:
            return vocabSkin.palette.destructive
        case .reviewDue:
            return vocabSkin.tierColor(for: "intermediate")
        }
    }

    private func resolveProgressTone(_ tone: ViewData.ReviewProgress.Tone) -> Color {
        switch tone {
        case .green:
            return vocabSkin.palette.success
        case .yellow:
            return vocabSkin.tierColor(for: "intermediate")
        case .orange:
            return vocabSkin.tierColor(for: "advanced")
        case .red:
            return vocabSkin.palette.destructive
        }
    }
}
