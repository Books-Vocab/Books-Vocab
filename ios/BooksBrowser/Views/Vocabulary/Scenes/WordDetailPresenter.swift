import SwiftUI

struct WordDetailPresenter: View {
    struct State {
        struct MetadataItem: Hashable {
            let icon: String
            let text: String
        }

        let title: String
        let systemImage: String
        let card: CardPresentation
        let rootForm: String?
        let metadataItems: [MetadataItem]
        let navigableLinkCardIDs: Set<String>
        let reviewProgress: VocabReviewProgress?
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

                    if let reviewProgress = state.reviewProgress {
                        CardSectionDivider()
                        reviewProgressSection(reviewProgress)
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

    private func reviewProgressSection(_ progress: VocabReviewProgress) -> some View {
        HStack {
            Text(progress.statusLabel.localized)
                .font(vocabSkin.typography.captionStrong)
                .foregroundStyle(vocabSkin.palette.secondaryText)

            Spacer()

            VocabReviewProgressBar(progress: progress)
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
