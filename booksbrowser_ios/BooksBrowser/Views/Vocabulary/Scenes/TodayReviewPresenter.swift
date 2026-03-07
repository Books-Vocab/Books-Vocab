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
    let canGoPrevious: Bool
    let canGoNext: Bool
}

struct TodayReviewPresenter: View {
    @Environment(\.vocabSkin) private var vocabSkin

    let state: TodayReviewPresenterState
    let onClose: () -> Void
    let onToggleCard: () -> Void
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

            Spacer()

            VocabChromeIconButton(systemImage: "xmark", action: onClose)
        }
        .padding(.horizontal, 20)
        .padding(.top, 10)
        .padding(.bottom, 6)
    }

    private func reviewCard(_ currentCard: TodayReviewPresenterState.CurrentCard) -> some View {
        VocabCard(padding: 0) {
            VStack(alignment: .leading, spacing: 0) {
                Button(action: onToggleCard) {
                    reviewCardFront(currentCard.card)
                }
                .buttonStyle(.plain)

                if state.showBack {
                    CardSectionDivider(horizontalPadding: AppMetrics.heroCardPadding)
                    reviewCardBack(currentCard)
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
                    .font(vocabSkin.typography.reviewWord)
                    .foregroundStyle(vocabSkin.palette.primaryText)
                    .lineLimit(3)
                    .minimumScaleFactor(0.6)
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
                Text(state.showBack ? "點擊收合" : "點擊翻面")
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)
            }
        }
        .padding(reviewCardPadding)
        .frame(minHeight: state.showBack ? nil : 300)
    }

    private func reviewCardBack(_ currentCard: TodayReviewPresenterState.CurrentCard) -> some View {
        let card = currentCard.card

        return VStack(alignment: .leading, spacing: 16) {
            switch card.reviewMode {
            case .recognition:
                Text(card.translation)
                    .font(vocabSkin.typography.translationTitle)
                    .foregroundStyle(vocabSkin.palette.translationText)
            case .production:
                Text(card.word)
                    .font(vocabSkin.typography.detailWord)
                    .foregroundStyle(vocabSkin.palette.primaryText)
                    .lineLimit(3)
                    .minimumScaleFactor(0.6)
            }

            if let example = card.examples.first {
                CardRichTextRenderer.text(
                    example,
                    style: CardRichTextStyle(
                        font: vocabSkin.typography.example,
                        textColor: vocabSkin.palette.secondaryText,
                        highlightColor: vocabSkin.palette.highlightMark,
                        italic: true
                    ),
                    truncateAroundMarkedWordRadius: 5
                )
                .lineSpacing(4)
            }

            if let explanation = card.explanation, !explanation.isEmpty {
                CardSectionDivider(horizontalPadding: reviewCardPadding)

                CardExplanationSection(explanation: explanation, colorScheme: .light)
                    .lineSpacing(4)
            }

            if !currentCard.linkGroups.isEmpty {
                CardSectionDivider(horizontalPadding: reviewCardPadding)
                reviewLinkStrip(currentCard.linkGroups)
            }
        }
        .padding(reviewCardPadding)
        .transition(.opacity.combined(with: .move(edge: .top)))
    }

    private var bottomToolbar: some View {
        HStack(spacing: 0) {
            HStack(spacing: AppMetrics.spacingSmall) {
                Button(action: onPrevious) {
                    Image(systemName: "chevron.left")
                        .font(.system(size: 16, weight: .thin))
                }
                .disabled(!state.canGoPrevious)

                Button(action: onNext) {
                    Image(systemName: "chevron.right")
                        .font(.system(size: 16, weight: .thin))
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
                .font(.system(size: 13, weight: .thin))
                .foregroundStyle(vocabSkin.palette.tertiaryText)
                .padding(.top, 2)

            VStack(alignment: .leading, spacing: 6) {
                ForEach(groups) { group in
                    HStack(spacing: 4) {
                        Text("\(group.label)：")
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.tertiaryText)

                        ForEach(Array(group.items.enumerated()), id: \.element.id) { index, item in
                            Button {
                                onLinkTap(item)
                            } label: {
                                Text(item.word)
                                    .font(.system(size: 16, weight: .semibold, design: .monospaced))
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
            return "先想意思，再點卡片翻面"
        case .production:
            return "先想英文，再點卡片翻面"
        }
    }

    private var reviewCardPadding: CGFloat {
        24
    }
}
