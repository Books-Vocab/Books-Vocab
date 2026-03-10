import SwiftUI

struct WordDetailPresenter: View {
    struct State {
        struct MetadataItem: Hashable {
            let icon: String
            let text: String
        }

        struct ReviewInfo {
            let stateLabel: String
            let stateTone: VocabActionTone
            let nextReviewLabel: String?
            let intervalLabel: String?
            let reviewCountLabel: String?
            let streakLabel: String?
        }

        let title: String
        let systemImage: String
        let card: CardPresentation
        let rootForm: String?
        let metadataItems: [MetadataItem]
        let navigableLinkCardIDs: Set<String>
        let reviewInfo: ReviewInfo?
    }

    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.vocabSkin) private var vocabSkin

    let state: State
    let wrapInNavigation: Bool
    let onClose: (() -> Void)?
    let onLinkTapped: (KGCardLinkSummary) -> Void

    var body: some View {
        Group {
            if wrapInNavigation {
                VStack(spacing: 0) {
                    VocabOverlayHeader(
                        title: state.title,
                        systemImage: state.systemImage,
                        onClose: { onClose?() }
                    )

                    detailContentScroll
                }
                .vocabCanvasBackground()
            } else {
                detailContentScroll
            }
        }
    }

    private var detailContentScroll: some View {
        ScrollView {
            VocabCard(padding: 0) {
                VStack(alignment: .leading, spacing: 0) {
                    CardDocumentView(document: state.card.document)

                    if !state.card.forms.isEmpty {
                        CardSectionDivider()
                        CardFormsSection(
                            forms: state.card.forms,
                            rootForm: state.rootForm,
                            colorScheme: colorScheme
                        )
                        .padding(vocabSkin.metrics.cardBlockPadding)
                    }

                    if !state.card.linkGroups.isEmpty {
                        CardSectionDivider()
                        linksSection
                            .padding(vocabSkin.metrics.cardBlockPadding)
                    }

                    if let reviewInfo = state.reviewInfo {
                        CardSectionDivider()
                        reviewInfoSection(reviewInfo)
                            .padding(vocabSkin.metrics.cardBlockPadding)
                    }

                    CardSectionDivider()
                    metadataFooter
                        .padding(vocabSkin.metrics.cardBlockPadding)
                }
            }
            .padding(vocabSkin.metrics.cardBlockPadding)
            .padding(.bottom, vocabSkin.metrics.cardBlockPadding * 2)
        }
        .scrollContentBackground(.hidden)
        .vocabCanvasBackground()
        .animation(AppMotion.contentFade, value: state.title)
    }

    private var linksSection: some View {
        VStack(alignment: .leading, spacing: vocabSkin.metrics.cardBlockContentGap) {
            CardSectionLabel(title: "知識連結", systemImage: "link")

            ForEach(state.card.linkGroups) { group in
                VStack(alignment: .leading, spacing: vocabSkin.metrics.cardBlockInnerGap) {
                    Text(group.label.localized)
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.tertiaryText)

                    ForEach(group.items) { link in
                        WordDetailGraphLinkRow(
                            link: link,
                            onTap: state.navigableLinkCardIDs.contains(link.cardId) ? {
                                onLinkTapped(link)
                            } : nil
                        )
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func reviewInfoSection(_ info: State.ReviewInfo) -> some View {
        VStack(alignment: .leading, spacing: vocabSkin.metrics.cardBlockInnerGap) {
            HStack {
                Text(info.stateLabel.localized)
                    .font(vocabSkin.typography.captionStrong)
                    .foregroundStyle(reviewToneColor(info.stateTone))
                    .padding(.horizontal, vocabSkin.spacing.compactChipHorizontalPadding)
                    .padding(.vertical, vocabSkin.spacing.compactChipVerticalPadding)
                    .background(reviewToneColor(info.stateTone).opacity(0.12))
                    .clipShape(RoundedRectangle(cornerRadius: vocabSkin.radii.chip, style: .continuous))

                Spacer()

                if let nextReviewLabel = info.nextReviewLabel {
                    Text(nextReviewLabel.localized)
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.tertiaryText)
                }
            }

            let chips: [String] = [info.intervalLabel, info.reviewCountLabel, info.streakLabel]
                .compactMap { $0 }
            if !chips.isEmpty {
                HStack(spacing: vocabSkin.spacing.microGap) {
                    ForEach(Array(chips.enumerated()), id: \.offset) { _, chip in
                        Text(chip.localized)
                            .font(vocabSkin.typography.monoLabel)
                            .foregroundStyle(vocabSkin.palette.quaternaryText)
                            .padding(.horizontal, vocabSkin.spacing.compactChipHorizontalPadding)
                            .padding(.vertical, vocabSkin.spacing.compactChipVerticalPadding)
                            .background(vocabSkin.palette.mutedFill)
                            .clipShape(RoundedRectangle(cornerRadius: vocabSkin.radii.tiny, style: .continuous))
                    }
                }
            }
        }
    }

    private func reviewToneColor(_ tone: VocabActionTone) -> Color {
        switch tone {
        case .primary:
            return vocabSkin.palette.accent
        case .neutral:
            return vocabSkin.palette.tertiaryText
        case .success:
            return vocabSkin.palette.success
        case .warning:
            return vocabSkin.palette.warning
        case .destructive:
            return vocabSkin.palette.destructive
        }
    }

    private var metadataFooter: some View {
        HStack(spacing: vocabSkin.metrics.cardBlockPadding) {
            ForEach(Array(state.metadataItems.enumerated()), id: \.offset) { _, item in
                HStack(spacing: 4) {
                    Image(systemName: item.icon)
                        .font(vocabSkin.typography.iconTiny)
                    Text(item.text.localized)
                }
            }
        }
        .font(vocabSkin.typography.caption)
        .foregroundStyle(vocabSkin.palette.quaternaryText)
    }
}
