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

        struct DictionaryState: Equatable {
            let detail: DictionaryDetailPresentation
            let cardRole: VocabularyCardRole
            let promotionState: VocabularyPromotionState
            let promotionFailure: DictionaryPromotionFailure?
            let promotionRetryable: Bool
        }

        let title: String
        let systemImage: String
        let card: CardPresentation
        let rootForm: String?
        let metadataItems: [MetadataItem]
        let navigableLinkCardIDs: Set<String>
        let reviewProgress: VocabReviewProgress?
        let dictionary: DictionaryState?

        var shareText: String {
            dictionary?.detail.shareText ?? card.document.plainTextExport()
        }
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
    let onSelectDictionary: ((LexicalSense, LexicalExample?) -> Void)?
    let onPromote: (() -> Void)?
    let onArchiveDictionary: (() -> Void)?
    let onDeleteDictionary: (() -> Void)?

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
                            if let onEdit, state.dictionary?.cardRole != .dictionary {
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

                    if let dictionary = state.dictionary {
                        CardSectionDivider()
                        dictionarySection(dictionary)
                            .padding(appSkin.metrics.cardBlockPadding)
                    }

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


            if let dictionary = state.dictionary, dictionary.cardRole == .dictionary {
                dictionaryActions(dictionary)
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
                                AppRoundedRect(roundness: AppRoundness.pill)
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
                    AppRoundedRect(roundness: AppRoundness.pill)
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
        ShareLink(item: state.shareText, subject: Text(state.title)) {
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

    @ViewBuilder
    private func dictionarySection(_ dictionary: State.DictionaryState) -> some View {
        if dictionary.cardRole == .learning {
            DisclosureGroup(L10n.string("dictionary.detail.provenance")) {
                dictionaryContent(dictionary.detail)
                    .padding(.top, appSkin.metrics.cardBlockInnerGap)
            }
            .font(appSkin.typography.caption)
            .foregroundStyle(appSkin.palette.secondaryText)
        } else {
            dictionaryContent(dictionary.detail)
        }
    }

    private func dictionaryContent(_ detail: DictionaryDetailPresentation) -> some View {
        VStack(alignment: .leading, spacing: appSkin.metrics.cardBlockContentGap) {
            HStack(spacing: appSkin.metrics.cardBlockInnerGap) {
                if !detail.pronunciations.isEmpty {
                    Text(detail.pronunciations.joined(separator: " · "))
                        .font(appSkin.typography.monoBody)
                        .foregroundStyle(appSkin.palette.secondaryText)
                }
                Spacer()
                if let partOfSpeech = detail.selectedSense.partOfSpeech {
                    Text(partOfSpeech)
                        .font(appSkin.typography.caption)
                        .foregroundStyle(appSkin.palette.tertiaryText)
                }
            }

            dictionarySense(detail.selectedSense, selectedExample: detail.selectedExample, isSelected: true)

            ForEach(detail.otherSenses) { sense in
                dictionarySense(sense, selectedExample: nil, isSelected: false)
            }

            if !detail.translations.isEmpty {
                dictionaryValueGroup(
                    title: L10n.string("dictionary.detail.translations"),
                    values: detail.translations
                )
            }
            if !detail.forms.isEmpty {
                dictionaryValueGroup(
                    title: L10n.string("dictionary.detail.forms"),
                    values: detail.forms
                )
            }

            VStack(alignment: .leading, spacing: AppSpacing.s1) {
                CardSectionLabel(
                    title: L10n.string("dictionary.detail.source"),
                    systemImage: "checkmark.seal"
                )
                Text(detail.provenance.attributionText)
                Text(detail.provenance.provider)
                Text(detail.provenance.licenseName)
                if let url = URL(string: detail.provenance.sourceURL) {
                    Link(L10n.string("dictionary.detail.openSource"), destination: url)
                }
            }
            .font(appSkin.typography.caption)
            .foregroundStyle(appSkin.palette.tertiaryText)
        }
    }

    private func dictionarySense(
        _ sense: LexicalSense,
        selectedExample: LexicalExample?,
        isSelected: Bool
    ) -> some View {
        VStack(alignment: .leading, spacing: AppSpacing.s1) {
            HStack(alignment: .firstTextBaseline) {
                Text(sense.definition)
                    .font(appSkin.typography.body)
                    .fontWeight(isSelected ? .semibold : .regular)
                    .foregroundStyle(isSelected ? appSkin.palette.primaryText : appSkin.palette.secondaryText)
                Spacer()
                if isSelected {
                    Image(systemName: "pin.fill")
                        .foregroundStyle(appSkin.palette.accent)
                        .accessibilityLabel(L10n.string("dictionary.detail.selectedSense"))
                } else if let onSelectDictionary {
                    Button(L10n.string("dictionary.detail.select")) {
                        onSelectDictionary(sense, sense.examples.first)
                    }
                    .buttonStyle(.vocabAction(.neutral))
                }
            }

            ForEach(sense.examples) { example in
                let isPinnedExample = isSelected && selectedExample?.id == example.id
                Button {
                    onSelectDictionary?(sense, example)
                } label: {
                    HStack(alignment: .firstTextBaseline, spacing: AppSpacing.s1) {
                        Text(example.text)
                            .font(appSkin.typography.caption)
                            .foregroundStyle(appSkin.palette.tertiaryText)
                            .multilineTextAlignment(.leading)
                        if isPinnedExample {
                            Image(systemName: "pin.fill")
                                .font(appSkin.typography.iconTiny)
                                .foregroundStyle(appSkin.palette.accent)
                        }
                    }
                }
                .buttonStyle(.plain)
                .disabled(onSelectDictionary == nil || isPinnedExample)
            }
        }
        .accessibilityElement(children: .contain)
    }

    private func dictionaryValueGroup(title: String, values: [String]) -> some View {
        VStack(alignment: .leading, spacing: AppSpacing.s1) {
            Text(title)
                .font(appSkin.typography.caption)
                .foregroundStyle(appSkin.palette.tertiaryText)
            Text(values.joined(separator: " · "))
                .font(appSkin.typography.body)
                .foregroundStyle(appSkin.palette.secondaryText)
        }
    }

    private func dictionaryActions(_ dictionary: State.DictionaryState) -> some View {
        VStack(alignment: .leading, spacing: appSkin.metrics.cardBlockInnerGap) {
            switch dictionary.promotionState {
            case .queued, .running:
                HStack(spacing: appSkin.metrics.cardBlockInnerGap) {
                    ProgressView()
                        .controlSize(.small)
                    Text(L10n.string("dictionary.promotion.running"))
                }
                .font(appSkin.typography.caption)
                .foregroundStyle(appSkin.palette.secondaryText)
                .accessibilityIdentifier("dictionary.promotion.progress")
            case .failed:
                Text(dictionary.promotionFailure?.message ?? L10n.string("dictionary.promotion.error.unknown"))
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.destructive)
                if dictionary.promotionRetryable, let onPromote {
                    Button(L10n.string("dictionary.promotion.retry"), action: onPromote)
                        .buttonStyle(.vocabAction(.primary))
                }
            case .idle:
                if let onPromote {
                    Button(L10n.string("dictionary.promotion.action"), action: onPromote)
                        .buttonStyle(.vocabAction(.primary))
                }
            }

            HStack(spacing: appSkin.metrics.cardBlockInnerGap) {
                if let onArchiveDictionary {
                    Button(L10n.string("notebook.toolbar.archive"), action: onArchiveDictionary)
                        .buttonStyle(.vocabAction(.neutral))
                }
                if let onDeleteDictionary {
                    Button(L10n.string("dictionary.delete.action"), role: .destructive, action: onDeleteDictionary)
                        .buttonStyle(.vocabAction(.destructive))
                }
            }
        }
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
