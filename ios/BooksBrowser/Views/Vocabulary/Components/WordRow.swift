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
            let detailLabel: String?
            let fraction: Double?
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
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @ScaledMetric(relativeTo: .body) private var scaledProgressBarHeight: CGFloat = 5
    let viewData: ViewData

    private var usesCompactLayout: Bool {
        dynamicTypeSize < .accessibility1
    }

    private var accessibilityRowLabel: String {
        var parts: [String] = [viewData.word]
        if let pos = viewData.partOfSpeech { parts.append(pos) }
        if let translation = viewData.translation, !translation.isEmpty {
            parts.append(translation)
        }
        return parts.joined(separator: ", ")
    }

    private var accessibilityProgressDescription: String {
        guard let progress = viewData.reviewProgress else { return "" }
        var parts = [progress.statusLabel]
        if let fraction = progress.fraction {
            parts.append("進度 \(Int(fraction * 100))%")
        }
        if let detail = progress.detailLabel {
            parts.append(detail)
        }
        return parts.joined(separator: ", ")
    }

    var body: some View {
        HStack(alignment: .top, spacing: vocabSkin.spacing.wordRowHorizontalGap) {
            VStack(alignment: .leading, spacing: vocabSkin.spacing.wordRowVerticalGap) {
                HStack(alignment: .firstTextBaseline, spacing: vocabSkin.spacing.wordRowBaselineGap) {
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
                    reviewProgressRow(reviewProgress)
                }

                if let book = viewData.bookTitle, !book.isEmpty {
                    HStack(spacing: vocabSkin.spacing.metadataGap) {
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

            if usesCompactLayout,
               let tier = viewData.difficultyTier,
               viewData.reviewProgress == nil,
               !viewData.isStrikethrough {
                VStack(alignment: .trailing, spacing: vocabSkin.spacing.wordRowVerticalGap) {
                    VocabTierLabel(tier: tier)
                }
            }
        }
        .padding(.vertical, vocabSkin.spacing.compactRowVerticalPadding)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilityRowLabel)
        .accessibilityValue(accessibilityProgressDescription)
        .accessibilityHint("點兩下查看詳細資訊")
    }

    private func reviewProgressRow(_ progress: ViewData.ReviewProgress) -> some View {
        reviewProgressAccessory(progress)
            .padding(.top, vocabSkin.spacing.compactRowAccessoryTopInset)
    }

    @ViewBuilder
    private func reviewProgressAccessory(_ progress: ViewData.ReviewProgress) -> some View {
        if let fraction = progress.fraction {
            VStack(alignment: .trailing, spacing: vocabSkin.spacing.reviewProgressBarGap) {
                if let detailLabel = progress.detailLabel {
                    Text(detailLabel)
                        .font(vocabSkin.typography.monoLabel)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                }

                GeometryReader { proxy in
                    ZStack(alignment: .leading) {
                        Capsule(style: .continuous)
                            .fill(vocabSkin.palette.progressBarBackground)

                        Capsule(style: .continuous)
                            .fill(resolveProgressTone(progress.tone))
                            .frame(width: max(6, proxy.size.width * fraction))
                            .animation(AppMotion.controlEaseOut, value: fraction)
                    }
                    .accessibilityLabel("複習進度")
                    .accessibilityValue("\(Int(fraction * 100))%")
                }
                .frame(width: vocabSkin.metrics.progressBarWidth, height: scaledProgressBarHeight)
            }
        } else if let detailLabel = progress.detailLabel {
            Text(detailLabel)
                .font(vocabSkin.typography.monoLabel)
                .foregroundStyle(vocabSkin.palette.secondaryText)
        }
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
            return vocabSkin.palette.warning
        }
    }

    private func resolveProgressTone(_ tone: ViewData.ReviewProgress.Tone) -> Color {
        switch tone {
        case .green:
            return vocabSkin.palette.success
        case .yellow:
            return vocabSkin.palette.tierIntermediate
        case .orange:
            return vocabSkin.palette.tierAdvanced
        case .red:
            return vocabSkin.palette.destructive
        }
    }
}
