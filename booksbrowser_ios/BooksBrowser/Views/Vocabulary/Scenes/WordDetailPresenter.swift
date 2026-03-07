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
                        .padding(AppMetrics.spacingLarge)
                    }

                    if !state.card.linkGroups.isEmpty {
                        CardSectionDivider()
                        linksSection
                            .padding(AppMetrics.spacingLarge)
                    }

                    CardSectionDivider()
                    metadataFooter
                        .padding(AppMetrics.spacingLarge)
                }
            }
            .padding(AppMetrics.spacingLarge)
            .padding(.bottom, AppMetrics.spacingLarge * 2)
        }
        .scrollContentBackground(.hidden)
        .vocabCanvasBackground()
    }

    private var linksSection: some View {
        VStack(alignment: .leading, spacing: AppMetrics.spacingMedium) {
            CardSectionLabel(title: "知識連結", systemImage: "link")

            ForEach(state.card.linkGroups) { group in
                VStack(alignment: .leading, spacing: AppMetrics.spacingSmall) {
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

    private var metadataFooter: some View {
        HStack(spacing: AppMetrics.spacingLarge) {
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
