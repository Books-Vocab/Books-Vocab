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
        let isExcludedFromReader: Bool
    }

    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.vocabSkin) private var vocabSkin

    let state: State
    let showsChrome: Bool
    let onClose: (() -> Void)?
    let onEdit: (() -> Void)?
    let onLinkTapped: (KGCardLinkSummary) -> Void
    let onToggleExcludeFromReader: (() -> Void)?
    let onAddLink: (() -> Void)?
    let onDeleteLink: ((KGCardLinkSummary) -> Void)?
    let onHideLink: ((KGCardLinkSummary) -> Void)?
    let onUnhideLink: ((KGCardLinkSummary) -> Void)?

    var body: some View {
        Group {
            if showsChrome {
                VStack(spacing: 0) {
                    VocabOverlayHeader(
                        title: state.title,
                        systemImage: state.systemImage,
                        onClose: { onClose?() },
                        trailing: {
                            shareButton
                            if let onEdit {
                                VocabChromeIconButton(systemImage: "pencil", label: "編輯".localized, action: onEdit)
                            }
                        }
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
            VStack(alignment: .leading, spacing: 0) {
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

                        if !state.card.activeLinkGroups.isEmpty || !state.card.hiddenLinks.isEmpty || onAddLink != nil {
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

                if let onToggleExcludeFromReader {
                    excludeFromReaderToggle(onToggle: onToggleExcludeFromReader)
                        .padding(.horizontal, vocabSkin.metrics.cardBlockPadding)
                        .padding(.top, vocabSkin.metrics.cardBlockInnerGap)
                }

                Spacer()
                    .frame(height: vocabSkin.metrics.cardBlockPadding * 2)
            }
        }
        .scrollContentBackground(.hidden)
        .vocabCanvasBackground()
        .animateContentFade(state.title)
    }

    private var linksSection: some View {
        VStack(alignment: .leading, spacing: vocabSkin.metrics.cardBlockContentGap) {
            HStack {
                CardSectionLabel(title: "知識連結".localized, systemImage: "link")
                Spacer()
                if let onAddLink {
                    Button(action: onAddLink) {
                        Image(systemName: "plus")
                            .font(vocabSkin.typography.iconSmall)
                            .foregroundStyle(vocabSkin.palette.secondaryText)
                    }
                    .buttonStyle(.plain)
                }
            }

            ForEach(state.card.activeLinkGroups) { group in
                VStack(alignment: .leading, spacing: vocabSkin.metrics.cardBlockInnerGap) {
                    Text(group.label.localized)
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.tertiaryText)

                    ForEach(group.items) { link in
                        WordDetailGraphLinkRow(
                            link: link,
                            onTap: state.navigableLinkCardIDs.contains(link.cardId) ? {
                                onLinkTapped(link)
                            } : nil,
                            onDelete: onDeleteLink != nil ? { onDeleteLink?(link) } : nil,
                            onHide: onHideLink != nil ? { onHideLink?(link) } : nil,
                            onUnhide: onUnhideLink != nil ? { onUnhideLink?(link) } : nil
                        )
                    }
                }
            }

            if !state.card.hiddenLinks.isEmpty {
                CollocationFlowLayout(spacing: vocabSkin.metrics.cardBlockInnerGap) {
                    ForEach(state.card.hiddenLinks) { link in
                        Text(link.word)
                            .font(vocabSkin.typography.monoBody)
                            .foregroundStyle(vocabSkin.palette.quaternaryText)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 4)
                            .background(
                                Capsule()
                                    .fill(vocabSkin.palette.divider.opacity(0.5))
                            )
                            .contextMenu {
                                if let onUnhide = onUnhideLink {
                                    Button {
                                        onUnhide(link)
                                    } label: {
                                        Label("恢復連結".localized, systemImage: "eye")
                                    }
                                }
                                if let onDelete = onDeleteLink {
                                    Button(role: .destructive) {
                                        onDelete(link)
                                    } label: {
                                        Label("刪除連結".localized, systemImage: "trash")
                                    }
                                }
                            }
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

    @ViewBuilder
    private var shareButton: some View {
        ShareLink(item: state.card.document.plainTextExport(), subject: Text(state.title)) {
            VocabChromeSurface(
                fill: vocabSkin.palette.cardBackground,
                border: vocabSkin.palette.cardBorder
            ) {
                Image(systemName: "square.and.arrow.up")
                    .font(vocabSkin.typography.iconMedium)
                    .foregroundStyle(vocabSkin.palette.secondaryText)
                    .frame(width: vocabSkin.metrics.chromeButtonSize, height: vocabSkin.metrics.chromeButtonSize)
            }
        }
        .buttonStyle(.plain)
        .accessibilityLabel("分享".localized)
    }

    private func excludeFromReaderToggle(onToggle: @escaping () -> Void) -> some View {
        Button(action: onToggle) {
            HStack(spacing: vocabSkin.metrics.cardBlockInnerGap) {
                Image(systemName: state.isExcludedFromReader ? "checkmark.square.fill" : "square")
                    .font(vocabSkin.typography.body)
                    .foregroundStyle(
                        state.isExcludedFromReader
                            ? vocabSkin.palette.secondaryText
                            : vocabSkin.palette.tertiaryText
                    )

                Text("閱讀時不標記此單字".localized)
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
            }
        }
        .buttonStyle(.plain)
        .animateContentFade(state.isExcludedFromReader)
    }
}
