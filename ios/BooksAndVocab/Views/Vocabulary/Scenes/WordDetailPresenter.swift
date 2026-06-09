import SwiftUI

enum WordDetailInspectorMetrics {
    static let maxContentWidth: CGFloat = 640
    static let minReadableWidth: CGFloat = 320

    static func contentWidth(containerWidth: CGFloat) -> CGFloat {
        min(max(containerWidth, minReadableWidth), maxContentWidth)
    }
}

struct WordDetailPresenter: View {
    @ObserveInjection private var inject
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
    @Environment(\.appSkin) private var appSkin

    let state: State
    /// Live value（非 `state` 快照）— 由 `@Bindable entry` 直讀,確保勾選即時翻轉視覺。
    let isExcludedFromReader: Bool
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
        .enableInjection()
    }

    private var detailContentScroll: some View {
        GeometryReader { proxy in
            ScrollView {
                detailContent
                    .frame(
                        maxWidth: WordDetailInspectorMetrics.contentWidth(containerWidth: proxy.size.width),
                        alignment: .leading
                    )
                    .frame(maxWidth: .infinity, alignment: .center)
            }
            .scrollContentBackground(.hidden)
        }
        .vocabCanvasBackground()
        .animateContentFade(state.title)
    }

    private var detailContent: some View {
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
                        .padding(appSkin.metrics.cardBlockPadding)
                    }

                    if !state.card.activeLinkGroups.isEmpty || !state.card.hiddenLinks.isEmpty || onAddLink != nil {
                        CardSectionDivider()
                        linksSection
                            .padding(appSkin.metrics.cardBlockPadding)
                    }

                    if let reviewProgress = state.reviewProgress {
                        CardSectionDivider()
                        reviewProgressSection(reviewProgress)
                            .padding(appSkin.metrics.cardBlockPadding)
                    }

                    CardSectionDivider()
                    metadataFooter
                        .padding(appSkin.metrics.cardBlockPadding)
                }
            }
            .padding(appSkin.metrics.cardBlockPadding)

            if let onToggleExcludeFromReader {
                excludeFromReaderToggle(onToggle: onToggleExcludeFromReader)
                    .padding(.horizontal, appSkin.metrics.cardBlockPadding)
                    .padding(.top, appSkin.metrics.cardBlockInnerGap)
            }

            Spacer()
                .frame(height: appSkin.metrics.cardBlockPadding * 2)
        }
    }

    private var linksSection: some View {
        VStack(alignment: .leading, spacing: appSkin.metrics.cardBlockContentGap) {
            HStack {
                CardSectionLabel(title: "知識連結".localized, systemImage: "link")
                Spacer()
                if let onAddLink {
                    Button(action: onAddLink) {
                        Image(systemName: "plus")
                            .font(appSkin.typography.iconSmall)
                            .foregroundStyle(appSkin.palette.secondaryText)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(L10n.string("vocab.card.addLink"))
                }
            }

            ForEach(state.card.activeLinkGroups) { group in
                VStack(alignment: .leading, spacing: appSkin.metrics.cardBlockInnerGap) {
                    Text(group.label.localized)
                        .font(appSkin.typography.caption)
                        .foregroundStyle(appSkin.palette.tertiaryText)

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
                CollocationFlowLayout(spacing: appSkin.metrics.cardBlockInnerGap) {
                    ForEach(state.card.hiddenLinks) { link in
                        Text(link.word)
                            .font(appSkin.typography.monoBody)
                            .foregroundStyle(appSkin.palette.quaternaryText)
                            .padding(.horizontal, AppSpacing.s2)
                            .padding(.vertical, AppSpacing.s1)
                            .background(
                                Capsule()
                                    .fill(appSkin.palette.divider.opacity(0.5))
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
                .font(appSkin.typography.caption)
                .foregroundStyle(appSkin.palette.secondaryText)

            Spacer()

            VocabReviewProgressBar(progress: progress)
        }
    }

    private var metadataFooter: some View {
        CollocationFlowLayout(spacing: AppSpacing.s2) {
            ForEach(Array(state.metadataItems.enumerated()), id: \.offset) { _, item in
                HStack(spacing: AppSpacing.s1) {
                    Image(systemName: item.icon)
                        .font(appSkin.typography.iconTiny)
                    Text(item.text.localized)
                }
                .padding(.horizontal, AppSpacing.s2)
                .padding(.vertical, AppSpacing.s1)
                .background(
                    Capsule()
                        .fill(appSkin.palette.buttonIdleFill)
                )
            }
        }
        .font(appSkin.typography.caption)
        .foregroundStyle(appSkin.palette.quaternaryText)
    }

    @ViewBuilder
    private var shareButton: some View {
        ShareLink(item: state.card.document.plainTextExport(), subject: Text(state.title)) {
            VocabChromeSurface(
                fill: appSkin.palette.cardBackground,
                border: appSkin.palette.cardBorder
            ) {
                Image(systemName: "square.and.arrow.up")
                    .font(appSkin.typography.iconMedium)
                    .foregroundStyle(appSkin.palette.secondaryText)
                    .frame(width: appSkin.metrics.chromeButtonSize, height: appSkin.metrics.chromeButtonSize)
            }
        }
        .buttonStyle(.plain)
        .accessibilityLabel("分享".localized)
    }

    private func excludeFromReaderToggle(onToggle: @escaping () -> Void) -> some View {
        Button(action: onToggle) {
            HStack(spacing: appSkin.metrics.cardBlockInnerGap) {
                Image(systemName: isExcludedFromReader ? "checkmark.square.fill" : "square")
                    .font(appSkin.typography.body)
                    .foregroundStyle(
                        isExcludedFromReader
                            ? appSkin.palette.secondaryText
                            : appSkin.palette.tertiaryText
                    )

                Text("閱讀時不標記此單字".localized)
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.tertiaryText)
            }
        }
        .buttonStyle(.plain)
        .accessibilityValue(isExcludedFromReader ? L10n.string("a11y.toggle.on") : L10n.string("a11y.toggle.off"))
        .accessibilityAddTraits(.isToggle)
        .animateContentFade(isExcludedFromReader)
    }
}
