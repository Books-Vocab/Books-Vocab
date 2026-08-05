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
    /// 同為 live value。封存後 sheet 刻意不關,靠這顆圖示翻轉當回饋 **兼** undo 入口
    /// ——再按一次就是解除封存,所以不需要帶動作的 undo toast（AppToastCoordinator 也沒有）。
    let isArchived: Bool
    /// 尚未同步的卡不給封存:`archiveCard` 以 word + notebookId 打伺服器,server 上還
    /// 沒有這張卡就會 404。與其讓它失敗再回捲,不如不顯示。
    let canArchive: Bool
    let showsChrome: Bool
    let onClose: (() -> Void)?
    let onEdit: (() -> Void)?
    let onLinkTapped: (KGCardLinkSummary) -> Void
    let onToggleExcludeFromReader: (() -> Void)?
    let onToggleArchive: (() -> Void)?
    let onDelete: (() -> Void)?
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
                            archiveButton
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

            if hasCardManagement {
                cardManagementSection
                    .padding(.horizontal, appSkin.metrics.cardBlockPadding)
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

    private var hasCardManagement: Bool {
        onToggleExcludeFromReader != nil || onDelete != nil
    }

    /// 卡片生命週期控制區。刻意壓在內容最底、與卡片之間隔一條 `AppAirDivider`
    /// （hairline + 32pt margin，北極星二：border 退場、divider 進場）。
    ///
    /// 為什麼不跟封存並排在標題列：三個動作的可逆性差了兩個量級。封存完全可逆、頻率最高，
    /// 值得標題列的單擊成本；刪除不可逆且會連帶帶走複習紀錄與知識連結，把它放進閱讀時
    /// 反覆掃過的區域，等於訓練手指伸進一個會咬人的鄰居旁邊。
    @ViewBuilder
    private var cardManagementSection: some View {
        // divider 只在真的有破壞性動作要被分隔出來時才畫。連結卡疊層（唯一沒有生命週期
        // 動作的宿主）只剩那顆勾選框，不該因為這次改動被塞進一個沒有內容的分區——
        // 它原本就只是貼在卡片下方的一列。
        if onDelete != nil {
            AppAirDivider()
        }

        VStack(alignment: .leading, spacing: appSkin.metrics.cardBlockInnerGap) {
            if let onToggleExcludeFromReader {
                excludeFromReaderToggle(onToggle: onToggleExcludeFromReader)
            }

            if let onDelete {
                managementRow(
                    title: WordDetailCopy.delete,
                    systemImage: "trash",
                    tone: appSkin.palette.destructive,
                    action: onDelete
                )
            }
        }
    }

    private func managementRow(
        title: String,
        systemImage: String,
        tone: Color,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack(spacing: appSkin.metrics.cardBlockInnerGap) {
                Image(systemName: systemImage)
                    .font(appSkin.typography.body)
                Text(title)
                    .font(appSkin.typography.caption)
            }
            .foregroundStyle(tone)
            // 只擴垂直觸控目標到 HIG 44pt 下限,不往右吃滿整列 —— 破壞性動作不該有
            // 一條橫跨整個寬度的熱區。
            .frame(minHeight: 44, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder
    private var archiveButton: some View {
        if canArchive, let onToggleArchive {
            VocabChromeIconButton(
                systemImage: isArchived ? "archivebox.fill" : "archivebox",
                label: isArchived ? WordDetailCopy.unarchive : WordDetailCopy.archive,
                action: onToggleArchive
            )
            .animateContentFade(isArchived)
        }
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

                Text(WordDetailCopy.excludeFromReader)
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
