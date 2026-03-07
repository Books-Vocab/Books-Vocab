import SwiftUI

struct TodayReviewPresenterState {
    struct LinkGroup: Identifiable {
        let id: String
        let label: String
        let items: [KGCardLinkSummary]
        let overflowCount: Int
    }

    struct CurrentCard {
        let card: CardPresentation
        let linkGroups: [LinkGroup]
    }

    let progressText: String
    let currentCard: CurrentCard?
    let showBack: Bool
    let isExpanded: Bool
    let canShuffle: Bool
    let canGoPrevious: Bool
    let canGoNext: Bool
}

struct TodayReviewPresenter: View {
    @Environment(\.vocabSkin) private var vocabSkin

    let state: TodayReviewPresenterState
    let onClose: () -> Void
    let onToggleCard: () -> Void
    let onToggleExpansion: () -> Void
    let onShuffle: () -> Void
    let onPrevious: () -> Void
    let onNext: () -> Void
    let onForgot: () -> Void
    let onRemembered: () -> Void
    let onLinkTap: (KGCardLinkSummary) -> Void

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if let currentCard = state.currentCard {
                    topBar

                    ScrollView {
                        reviewCard(currentCard)
                            .padding(.horizontal, AppMetrics.spacingLarge)
                            .padding(.top, AppMetrics.spacingMedium)
                            .padding(.bottom, AppMetrics.spacingXXL)
                    }

                    bottomToolbar
                } else {
                    completionState
                }
            }
            .vocabCanvasBackground()
            .toolbar(.hidden, for: .navigationBar)
        }
    }

    private var topBar: some View {
        HStack(alignment: .center, spacing: 12) {
            Text(state.progressText)
                .font(vocabSkin.typography.monoLabel)
                .foregroundStyle(vocabSkin.palette.tertiaryText)
                .padding(.horizontal, 10)
                .padding(.vertical, 8)
                .background(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                        .fill(vocabSkin.palette.mutedFill)
                )

            Button(action: onShuffle) {
                HStack(spacing: 6) {
                    Image(systemName: "shuffle")
                        .font(vocabSkin.typography.iconTiny)
                    Text("洗牌")
                        .font(vocabSkin.typography.captionStrong)
                }
                .foregroundStyle(state.canShuffle ? vocabSkin.palette.secondaryText : vocabSkin.palette.quaternaryText)
                .padding(.horizontal, 10)
                .padding(.vertical, 8)
                .background(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                        .fill(vocabSkin.palette.mutedFill)
                )
            }
            .buttonStyle(.plain)
            .disabled(!state.canShuffle)

            Spacer()

            VocabChromeIconButton(systemImage: "xmark", action: onClose)
        }
        .padding(.horizontal, 20)
        .padding(.top, 10)
        .padding(.bottom, 6)
    }

    private func reviewCard(_ currentCard: TodayReviewPresenterState.CurrentCard) -> some View {
        VStack(spacing: 0) {
            if state.showBack {
                foldedReviewCard(currentCard)
            } else {
                VocabCard(padding: 0) {
                    Button(action: onToggleCard) {
                        reviewCardFront(currentCard.card)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private func reviewCardFront(_ card: CardPresentation) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 6) {
                if let pos = card.partOfSpeech {
                    Text(pos)
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.tertiaryText)
                }
                Spacer()
                if let tier = card.difficultyTier {
                    VocabTierLabel(tier: tier)
                }
            }

            Spacer(minLength: 18)

            switch card.reviewMode {
            case .recognition:
                Text(card.word)
                    .font(reviewWordFont(for: card.word))
                    .foregroundStyle(vocabSkin.palette.primaryText)
                    .lineLimit(4)
                    .minimumScaleFactor(0.5)
                    .fixedSize(horizontal: false, vertical: true)
            case .production:
                Text(card.translation)
                    .font(vocabSkin.typography.translationTitle)
                    .foregroundStyle(vocabSkin.palette.primaryText.opacity(0.84))
                    .minimumScaleFactor(0.6)
            }

            if card.reviewMode == .production, let example = card.examples.first {
                CardRichTextRenderer.text(
                    example,
                    style: CardRichTextStyle(
                        font: vocabSkin.typography.example,
                        textColor: vocabSkin.palette.secondaryText,
                        highlightColor: vocabSkin.palette.highlightMark,
                        italic: true
                    ),
                    mode: .cloze,
                    truncateAroundMarkedWordRadius: 5
                )
                .lineSpacing(4)
            }

            Spacer(minLength: 14)

            HStack {
                Text(frontInstruction(for: card.reviewMode))
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
                Spacer()
                Text((state.showBack ? "點擊收合" : "點擊翻面").localized)
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)
            }
        }
        .padding(reviewCardPadding)
        .frame(minHeight: state.showBack ? nil : 300)
    }

    private func foldedReviewCard(_ currentCard: TodayReviewPresenterState.CurrentCard) -> some View {
        let card = currentCard.card
        return VStack(spacing: 0) {
            topFoldSurface(expanded: state.isExpanded) {
                VStack(alignment: .leading, spacing: 0) {
                    reviewCardBackHeader(card)

                    Spacer(minLength: 0)

                    foldCue(expanded: state.isExpanded)
                }
                .padding(reviewCardPadding)
                .frame(minHeight: 300, alignment: .topLeading)
            }

            if state.isExpanded {
                unfoldedDetailSurface {
                    VStack(alignment: .leading, spacing: 16) {
                        CardDocumentView(document: reviewBackDocument(for: card))

                        if !currentCard.linkGroups.isEmpty {
                            CardSectionDivider(horizontalPadding: reviewCardPadding)
                            reviewLinkStrip(currentCard.linkGroups)
                        }
                    }
                    .padding(.horizontal, reviewCardPadding)
                    .padding(.top, 18)
                    .padding(.bottom, reviewCardPadding)
                }
                .transition(
                    .asymmetric(
                        insertion: .move(edge: .top).combined(with: .opacity),
                        removal: .opacity
                    )
                )
            }
        }
    }

    private var bottomToolbar: some View {
        HStack(spacing: 0) {
            HStack(spacing: AppMetrics.spacingSmall) {
                Button(action: onPrevious) {
                    Image(systemName: "chevron.left")
                        .font(vocabSkin.typography.iconNavigation)
                }
                .disabled(!state.canGoPrevious)

                Button(action: onNext) {
                    Image(systemName: "chevron.right")
                        .font(vocabSkin.typography.iconNavigation)
                }
                .disabled(!state.canGoNext)
            }
            .foregroundStyle(vocabSkin.palette.secondaryText)

            Spacer()

            if state.showBack {
                HStack(spacing: 10) {
                    Button(action: onForgot) {
                        Label("忘記", systemImage: "xmark")
                            .frame(minWidth: 92)
                    }
                    .buttonStyle(.vocabAction(.destructive))

                    Button(action: onRemembered) {
                        Label("記得", systemImage: "checkmark")
                            .frame(minWidth: 92)
                    }
                    .buttonStyle(.vocabAction(.success))
                }
                .transition(.opacity)
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 12)
        .background(
            Rectangle()
                .fill(vocabSkin.palette.pageBackground)
                .shadow(color: vocabSkin.palette.shadow.opacity(1.1), radius: 6, y: -2)
                .ignoresSafeArea(edges: .bottom)
        )
    }

    private var completionState: some View {
        VStack(spacing: AppMetrics.spacingLarge) {
            Spacer()
            VocabEmptyStateContent(
                title: "今天複習完成",
                systemImage: "checkmark.circle",
                description: "這一輪 session 的卡片都處理完了。"
            )
            Button("返回生詞庫", action: onClose)
                .buttonStyle(.ghost(vocabSkin.palette.primaryText))
            Spacer()
        }
        .padding(.horizontal, AppMetrics.spacingLarge)
    }

    private func reviewLinkStrip(_ groups: [TodayReviewPresenterState.LinkGroup]) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "paperclip")
                .font(vocabSkin.typography.iconTiny)
                .foregroundStyle(vocabSkin.palette.tertiaryText)
                .padding(.top, 2)

            VStack(alignment: .leading, spacing: 6) {
                ForEach(groups) { group in
                    HStack(spacing: 4) {
                        Text(group.label.localized + "：")
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.tertiaryText)

                        ForEach(Array(group.items.enumerated()), id: \.element.id) { index, item in
                            Button {
                                onLinkTap(item)
                            } label: {
                                Text(item.word)
                                    .font(vocabSkin.typography.monoEmphasis)
                                    .foregroundStyle(vocabSkin.palette.primaryText)
                            }
                            .buttonStyle(.plain)

                            if index < group.items.count - 1 {
                                Text("|")
                                    .font(vocabSkin.typography.caption)
                                    .foregroundStyle(vocabSkin.palette.quaternaryText)
                            }
                        }

                        if group.overflowCount > 0 {
                            Text("+\(group.overflowCount)")
                                .font(vocabSkin.typography.captionStrong)
                                .foregroundStyle(vocabSkin.palette.quaternaryText)
                        }
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func frontInstruction(for mode: VocabularyCardMode) -> String {
        switch mode {
        case .recognition:
            return L10n.string("先想意思，再點卡片翻面")
        case .production:
            return L10n.string("先想英文，再點卡片翻面")
        }
    }

    private var reviewCardPadding: CGFloat {
        24
    }

    private func reviewCardBackHeader(_ card: CardPresentation) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 6) {
                if let pos = card.partOfSpeech {
                    Text(pos)
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.tertiaryText)
                }
                Spacer()
                if let tier = card.difficultyTier {
                    VocabTierLabel(tier: tier)
                }
            }

            Spacer(minLength: 18)

            Group {
                if card.reviewMode == .production {
                    Text(card.word)
                } else {
                    Text(card.translation)
                }
            }
            .font(reviewWordFont(for: card.reviewMode == .production ? card.word : card.translation))
            .foregroundStyle(vocabSkin.palette.primaryText)
            .lineLimit(4)
            .minimumScaleFactor(0.5)
            .fixedSize(horizontal: false, vertical: true)

            Spacer(minLength: 14)

            HStack {
                Text("點擊上半張收回正面")
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
                Spacer()
                Text(state.isExpanded ? "已展開" : "點擊底部展開")
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)
            }
        }
        .contentShape(Rectangle())
        .onTapGesture(perform: onToggleCard)
    }

    private func foldCue(expanded: Bool) -> some View {
        Button(action: onToggleExpansion) {
            VStack(spacing: expanded ? 8 : 10) {
                RoundedRectangle(cornerRadius: vocabSkin.radii.tiny, style: .continuous)
                    .fill(vocabSkin.palette.quaternaryText.opacity(0.32))
                    .frame(width: 44, height: 4)

                HStack(spacing: 8) {
                    Image(systemName: expanded ? "chevron.up" : "chevron.down")
                        .font(vocabSkin.typography.iconTiny)
                    Text(expanded ? "收合折頁" : "展開折頁")
                        .font(vocabSkin.typography.captionStrong)
                }
                .foregroundStyle(vocabSkin.palette.tertiaryText)
            }
            .frame(maxWidth: .infinity)
            .frame(height: expanded ? 48 : 96)
            .background(
                Rectangle()
                    .fill(
                        LinearGradient(
                            colors: [
                                vocabSkin.palette.cardBackground.opacity(0.0),
                                vocabSkin.palette.mutedFill.opacity(0.65)
                            ],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                    )
            )
        }
        .buttonStyle(.plain)
        .contentShape(Rectangle())
    }

    private func topFoldSurface<Content: View>(expanded: Bool, @ViewBuilder content: () -> Content) -> some View {
        let shape = UnevenRoundedRectangle(
            topLeadingRadius: vocabSkin.radii.card,
            bottomLeadingRadius: expanded ? 4 : vocabSkin.radii.card,
            bottomTrailingRadius: expanded ? 4 : vocabSkin.radii.card,
            topTrailingRadius: vocabSkin.radii.card,
            style: .continuous
        )

        return content()
            .background(vocabSkin.palette.cardBackground)
            .clipShape(shape)
            .overlay(shape.stroke(vocabSkin.palette.cardBorder.opacity(0.72), lineWidth: 1))
            .shadow(color: vocabSkin.palette.shadow, radius: 6, y: 2)
    }

    private func unfoldedDetailSurface<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        let shape = UnevenRoundedRectangle(
            topLeadingRadius: 4,
            bottomLeadingRadius: vocabSkin.radii.card,
            bottomTrailingRadius: vocabSkin.radii.card,
            topTrailingRadius: 4,
            style: .continuous
        )

        return content()
            .background(vocabSkin.palette.cardBackground.opacity(0.985))
            .clipShape(shape)
            .overlay(shape.stroke(vocabSkin.palette.cardBorder.opacity(0.72), lineWidth: 1))
            .overlay(alignment: .top) {
                Rectangle()
                    .fill(vocabSkin.palette.divider.opacity(0.85))
                    .frame(height: 0.5)
                    .padding(.horizontal, 18)
            }
            .padding(.top, -2)
            .shadow(color: vocabSkin.palette.shadow.opacity(0.7), radius: 3, y: 1)
    }

    private func reviewWordFont(for text: String) -> Font {
        let count = text.count
        if count > 20 { return vocabSkin.typography.translationTitle }
        if count > 12 { return .system(size: 28, weight: .semibold, design: .monospaced) }
        return vocabSkin.typography.reviewWord
    }

    private func reviewBackDocument(for card: CardPresentation) -> CardDocument {
        let blocks = card.document.blocks.compactMap { block -> CardDocumentBlock? in
            switch block {
            case .hero, .source:
                return nil
            case .example, .divider, .meaning:
                return block
            }
        }

        return CardDocument(blocks: blocks)
    }
}
