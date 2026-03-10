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
    let revealStage: TodayReviewRevealStage
    let canShuffle: Bool
    let canGoPrevious: Bool
    let canGoNext: Bool
    let rememberedFeedbackTrigger: Int
    let forgotFeedbackTrigger: Int
    let persistenceFailureTrigger: Int
    let persistenceErrorMessage: String?
}

struct TodayReviewPresenter: View {
    @Environment(\.vocabSkin) private var vocabSkin

    let state: TodayReviewPresenterState
    let onClose: () -> Void
    let onAdvanceReveal: () -> Void
    let onCollapseReveal: () -> Void
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

                    GeometryReader { geo in
                        ScrollView {
                            VStack(spacing: 0) {
                                reviewCard(currentCard)
                                    .id(currentCard.card.word + "-" + String(currentCard.card.dateAdded.timeIntervalSinceReferenceDate))
                                    .transition(.reviewCardSwap)
                                    .padding(.horizontal, vocabSkin.metrics.reviewCardHorizontalInset)
                                    .padding(.top, vocabSkin.metrics.reviewCardTopInset)
                                    .padding(.bottom, vocabSkin.metrics.reviewCardBottomInset)

                                if state.revealStage == .front {
                                    revealExpandZone(
                                        title: "點一下展開",
                                        minHeight: max(geo.size.height * 0.28, 180),
                                        action: onAdvanceReveal
                                    )
                                } else if state.revealStage == .back {
                                    revealExpandZone(
                                        title: "點一下查看細節",
                                        minHeight: max(geo.size.height * 0.22, 140),
                                        action: onAdvanceReveal
                                    )
                                } else if state.revealStage.showsAnswer {
                                    Spacer(minLength: 0)
                                }
                            }
                            .frame(maxWidth: .infinity, minHeight: geo.size.height, alignment: .top)
                        }
                    }

                    bottomToolbar
                } else {
                    completionState
                }
            }
            .vocabCanvasBackground()
            .toolbar(.hidden, for: .navigationBar)
            .sensoryFeedback(.success, trigger: state.rememberedFeedbackTrigger)
            .sensoryFeedback(.warning, trigger: state.forgotFeedbackTrigger)
            .sensoryFeedback(.error, trigger: state.persistenceFailureTrigger)
        }
    }

    private var topBar: some View {
        HStack(alignment: .center, spacing: 12) {
            Text(state.progressText)
                .font(vocabSkin.typography.monoLabel)
                .foregroundStyle(vocabSkin.palette.tertiaryText)
                .padding(.horizontal, vocabSkin.spacing.chipHorizontalPadding)
                .padding(.vertical, vocabSkin.spacing.chipVerticalPadding + 2)
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
                .padding(.horizontal, vocabSkin.spacing.chipHorizontalPadding)
                .padding(.vertical, vocabSkin.spacing.chipVerticalPadding + 2)
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
        .padding(.horizontal, vocabSkin.metrics.reviewTopBarHorizontalInset)
        .padding(.top, vocabSkin.metrics.reviewTopBarTopInset)
        .padding(.bottom, vocabSkin.metrics.reviewTopBarBottomInset)
    }

    private func reviewCard(_ currentCard: TodayReviewPresenterState.CurrentCard) -> some View {
        VStack(spacing: 0) {
            frontFoldSurface(currentCard.card)

            if state.revealStage.showsAnswer {
                answerFoldSurface(currentCard.card)
                    .padding(.top, -1)
                    .transition(.paperFoldFromTop)
            }

            if state.revealStage.showsDetails {
                detailFoldSheet(currentCard)
                    .padding(.top, -1)
                    .transition(.paperFoldFromTop)
            }
        }
        .animation(AppMotion.reviewRevealSpring, value: state.revealStage)
    }

    private func reviewCardFront(_ card: CardPresentation) -> some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            HStack(spacing: 6) {
                if let pos = card.partOfSpeech {
                    Text(pos)
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.tertiaryText)
                }
                Spacer()
            }

            Spacer(minLength: vocabSkin.metrics.reviewFoldHintBottomInset)

            switch card.reviewMode {
            case .recognition:
                Text(card.word)
                    .font(reviewFrontWordFont(for: card.word))
                    .foregroundStyle(vocabSkin.palette.primaryText)
                    .lineLimit(3)
                    .minimumScaleFactor(0.7)
                    .fixedSize(horizontal: false, vertical: true)
            case .production:
                Text(card.translation)
                    .font(vocabSkin.typography.body.weight(.semibold))
                    .foregroundStyle(vocabSkin.palette.primaryText.opacity(0.84))
                    .minimumScaleFactor(0.75)
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

            Spacer(minLength: vocabSkin.metrics.reviewTopBarTopInset)
        }
        .padding(reviewCardPadding)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .frame(height: frontCardHeight, alignment: .topLeading)
    }

    private func frontFoldSurface(_ card: CardPresentation) -> some View {
        foldSurface(position: state.revealStage.showsAnswer ? .top : .single) {
            Button(action: onAdvanceReveal) {
                reviewCardFront(card)
                    .frame(maxWidth: .infinity, alignment: .topLeading)
                    .frame(height: frontCardHeight, alignment: .topLeading)
            }
            .buttonStyle(.plain)
            .frame(maxWidth: .infinity, alignment: .topLeading)
            .frame(height: frontCardHeight, alignment: .topLeading)
            .contentShape(Rectangle())
            .disabled(state.revealStage.showsAnswer)
        }
    }

    private func revealExpandZone(
        title: String,
        minHeight: CGFloat,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            VStack(spacing: 10) {
                Capsule(style: .continuous)
                    .fill(vocabSkin.palette.quaternaryText.opacity(0.14))
                    .frame(width: 56, height: 3)

                Text(title)
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.quaternaryText.opacity(0.72))
            }
            .frame(maxWidth: .infinity)
            .frame(minHeight: minHeight, alignment: .top)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private var bottomToolbar: some View {
        VStack(spacing: 10) {
            if let persistenceErrorMessage = state.persistenceErrorMessage {
                VocabStateMessageCard(
                    title: "本機儲存失敗",
                    systemImage: "externaldrive.badge.exclamationmark",
                    description: persistenceErrorMessage
                )
                .transition(.overlayFade)
            }

            HStack(spacing: 0) {
                HStack(spacing: vocabSkin.spacing.inlineGap) {
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

                if state.revealStage.showsAnswer {
                    HStack(spacing: vocabSkin.metrics.sectionHeaderGap) {
                        Button(action: onForgot) {
                            Label("忘記", systemImage: "xmark")
                                .frame(minWidth: vocabSkin.metrics.reviewActionMinWidth)
                        }
                        .buttonStyle(.vocabAction(.destructive))

                        Button(action: onRemembered) {
                            Label("記得", systemImage: "checkmark")
                                .frame(minWidth: vocabSkin.metrics.reviewActionMinWidth)
                        }
                        .buttonStyle(.vocabAction(.success))
                    }
                    .transition(.overlayFade)
                }
            }
        }
        .padding(.horizontal, vocabSkin.metrics.reviewToolbarHorizontalInset)
        .padding(.vertical, vocabSkin.metrics.reviewToolbarVerticalInset)
        .animation(AppMotion.reviewNavigationSpring, value: state.revealStage.showsAnswer)
        .animation(AppMotion.phaseChange, value: state.persistenceErrorMessage)
        .background(
            Rectangle()
                .fill(vocabSkin.palette.pageBackground)
                .shadow(
                    color: vocabSkin.palette.shadow.opacity(vocabSkin.metrics.reviewToolbarShadowOpacity),
                    radius: vocabSkin.metrics.reviewToolbarShadowRadius,
                    y: vocabSkin.metrics.reviewToolbarShadowY
                )
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
        HStack(alignment: .top, spacing: vocabSkin.spacing.inlineGap) {
            Image(systemName: "paperclip")
                .font(vocabSkin.typography.iconTiny)
                .foregroundStyle(vocabSkin.palette.tertiaryText)
                .padding(.top, 2)

            VStack(alignment: .leading, spacing: vocabSkin.spacing.inlineGap) {
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

    private var reviewCardPadding: CGFloat {
        vocabSkin.metrics.reviewFoldPadding
    }

    private var frontCardHeight: CGFloat {
        vocabSkin.metrics.reviewFrontMinHeight
    }

    private var answerCardHeight: CGFloat {
        vocabSkin.metrics.reviewAnswerMinHeight
    }

    private func answerFoldSurface(_ card: CardPresentation) -> some View {
        foldSurface(position: state.revealStage.showsDetails ? .middle : .bottom) {
            ZStack(alignment: .topTrailing) {
                if state.revealStage == .back {
                    Button(action: onAdvanceReveal) {
                        answerFoldContent(card, showsExpandHint: true)
                    }
                    .buttonStyle(.plain)
                    .contentShape(Rectangle())
                } else {
                    answerFoldContent(card, showsExpandHint: false)
                }

                if !state.revealStage.showsDetails {
                    foldChevronButton(action: onCollapseReveal)
                        .padding(reviewCardPadding)
                }
            }
        }
    }

    private func answerFoldContent(_ card: CardPresentation, showsExpandHint: Bool) -> some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            HStack(spacing: 6) {
                Spacer()
                if let tier = card.difficultyTier {
                    VocabTierLabel(tier: tier)
                }
            }

            Spacer(minLength: vocabSkin.metrics.reviewFoldHintTopInset)

            Group {
                if card.reviewMode == .production {
                    Text(card.word)
                } else {
                    Text(card.translation)
                }
            }
            .font(reviewAnswerWordFont(for: card.reviewMode == .production ? card.word : card.translation))
            .foregroundStyle(vocabSkin.palette.primaryText)
            .lineLimit(4)
            .minimumScaleFactor(0.65)
            .fixedSize(horizontal: false, vertical: true)

            if let pronunciation = card.pronunciation, !pronunciation.isEmpty {
                Text("/\(pronunciation)/")
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)
            }

            Spacer(minLength: 0)
        }
        .padding(reviewCardPadding)
        .padding(.trailing, showsExpandHint ? 40 : 0)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .frame(height: answerCardHeight, alignment: .topLeading)
    }

    private func detailFoldSheet(_ currentCard: TodayReviewPresenterState.CurrentCard) -> some View {
        let card = currentCard.card
        return foldSurface(position: .bottom) {
            VStack(alignment: .leading, spacing: vocabSkin.metrics.reviewFoldSectionSpacing) {
                HStack {
                    Spacer()
                    foldChevronButton(action: onCollapseReveal)
                }

                CardDocumentView(document: reviewBackDocument(for: card))

                if !currentCard.linkGroups.isEmpty {
                    CardSectionDivider(horizontalPadding: 0)
                    reviewLinkStrip(currentCard.linkGroups)
                }
            }
            .padding(.horizontal, reviewCardPadding)
            .padding(.top, vocabSkin.metrics.reviewToolbarVerticalInset)
            .padding(.bottom, reviewCardPadding)
        }
    }

    private func foldSurface<Content: View>(
        position: FoldSegmentPosition,
        @ViewBuilder content: () -> Content
    ) -> some View {
        content()
            .background(vocabSkin.palette.cardBackground.opacity(0.985))
            .clipShape(foldShape(for: position))
            .overlay(foldShape(for: position).stroke(vocabSkin.palette.cardBorder.opacity(0.72), lineWidth: 1))
            .overlay(alignment: .top) {
                if position != .top && position != .single {
                        Rectangle()
                            .fill(vocabSkin.palette.divider.opacity(0.85))
                            .frame(height: 0.5)
                            .padding(.horizontal, vocabSkin.spacing.cardPadding)
                }
            }
            .shadow(color: vocabSkin.palette.shadow.opacity(position == .single ? 1 : 0.7), radius: 6, y: 2)
    }

    private func foldShape(for position: FoldSegmentPosition) -> UnevenRoundedRectangle {
        let topRadius = position == .single || position == .top ? vocabSkin.radii.card : 4
        let bottomRadius = position == .single || position == .bottom ? vocabSkin.radii.card : 4

        return UnevenRoundedRectangle(
            topLeadingRadius: topRadius,
            bottomLeadingRadius: bottomRadius,
            bottomTrailingRadius: bottomRadius,
            topTrailingRadius: topRadius,
            style: .continuous
        )
    }

    private func reviewFrontWordFont(for text: String) -> Font {
        let count = text.count
        if count > 20 { return .system(size: 22, weight: .semibold, design: .monospaced) }
        if count > 12 { return .system(size: 26, weight: .semibold, design: .monospaced) }
        return .system(size: 30, weight: .semibold, design: .monospaced)
    }

    private func reviewAnswerWordFont(for text: String) -> Font {
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

    private func foldChevronButton(action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: "chevron.up")
                .font(vocabSkin.typography.iconTiny.weight(.bold))
                .foregroundStyle(vocabSkin.palette.secondaryText)
                .frame(width: vocabSkin.metrics.reviewChevronButtonSize, height: vocabSkin.metrics.reviewChevronButtonSize)
                .background(
                    Circle()
                        .fill(vocabSkin.palette.mutedFill.opacity(0.96))
                )
                .overlay(
                    Circle()
                        .stroke(vocabSkin.palette.cardBorder.opacity(0.72), lineWidth: 1)
                )
        }
        .buttonStyle(.plain)
        .contentShape(Circle())
    }

    private func foldExpandHint(title: String) -> some View {
        VStack(spacing: 8) {
            Capsule(style: .continuous)
                .fill(vocabSkin.palette.quaternaryText.opacity(0.24))
                .frame(width: vocabSkin.metrics.reviewHintCapsuleWidth, height: 4)

            Text(title)
                .font(vocabSkin.typography.caption)
                .foregroundStyle(vocabSkin.palette.tertiaryText)
        }
        .frame(maxWidth: .infinity)
    }
}

private enum FoldSegmentPosition {
    case single
    case top
    case middle
    case bottom
}

private enum TodayReviewPresenterPreviewData {
    static let baseCard: CardPresentation = {
        let entry = VocabularyEntry(
            word: "meticulous",
            translation: "一絲不苟的；非常仔細的",
            context: "The editor was meticulous about every line break and caption.",
            explanation: "描述做事非常細心、注意細節，通常帶有正面稱讚意味。",
            partOfSpeech: "adj.",
            pronunciation: "məˈtɪkjələs",
            bookTitle: "Designing Interfaces",
            chapterTitle: "Writing Tone"
        )
        entry.dateAdded = Date(timeIntervalSince1970: 1_736_000_000)
        entry.difficultyTier = "advanced"
        entry.reviewMode = .recognition
        entry.reviewExamples = ["The editor was meticulous about every line break and caption."]
        entry.syncState = .synced
        entry.rootForm = "meticulous"
        entry.inflections = ["meticulously", "meticulousness"]
        entry.graphLinksByKind = [
            "confusable": [
                KGCardLinkSummary(id: "link-1", cardId: "card-1", word: "precise", kind: "confusable", label: "易混", confidence: 0.82, reason: "都與精確相關"),
                KGCardLinkSummary(id: "link-2", cardId: "card-2", word: "thorough", kind: "confusable", label: "易混", confidence: 0.79, reason: "都與仔細相關"),
                KGCardLinkSummary(id: "link-3", cardId: "card-3", word: "scrupulous", kind: "confusable", label: "易混", confidence: 0.75, reason: "都與嚴謹相關")
            ]
        ]
        return entry.cardPresentation
    }()

    static let currentCard = TodayReviewPresenterState.CurrentCard(
        card: baseCard,
        linkGroups: [
            .init(
                id: "confusable",
                label: "易混",
                items: [
                    .init(id: "link-1", cardId: "card-1", word: "precise", kind: "confusable", label: "易混", confidence: 0.82, reason: "都與精確相關"),
                    .init(id: "link-2", cardId: "card-2", word: "thorough", kind: "confusable", label: "易混", confidence: 0.79, reason: "都與仔細相關")
                ],
                overflowCount: 1
            )
        ]
    )

    static func state(stage: TodayReviewRevealStage) -> TodayReviewPresenterState {
        .init(
            progressText: "3 / 12",
            currentCard: currentCard,
            revealStage: stage,
            canShuffle: true,
            canGoPrevious: true,
            canGoNext: true,
            rememberedFeedbackTrigger: 0,
            forgotFeedbackTrigger: 0,
            persistenceFailureTrigger: 0,
            persistenceErrorMessage: nil
        )
    }

    static let completedState = TodayReviewPresenterState(
        progressText: "12 / 12",
        currentCard: nil,
        revealStage: .front,
        canShuffle: false,
        canGoPrevious: false,
        canGoNext: false,
        rememberedFeedbackTrigger: 0,
        forgotFeedbackTrigger: 0,
        persistenceFailureTrigger: 0,
        persistenceErrorMessage: nil
    )
}

#Preview("Today Review / Front") {
    AppThemeContainer {
        TodayReviewPresenter(
            state: TodayReviewPresenterPreviewData.state(stage: .front),
            onClose: {},
            onAdvanceReveal: {},
            onCollapseReveal: {},
            onShuffle: {},
            onPrevious: {},
            onNext: {},
            onForgot: {},
            onRemembered: {},
            onLinkTap: { _ in }
        )
    }
}

#Preview("Today Review / Details") {
    AppThemeContainer {
        TodayReviewPresenter(
            state: TodayReviewPresenterPreviewData.state(stage: .details),
            onClose: {},
            onAdvanceReveal: {},
            onCollapseReveal: {},
            onShuffle: {},
            onPrevious: {},
            onNext: {},
            onForgot: {},
            onRemembered: {},
            onLinkTap: { _ in }
        )
    }
}

#Preview("Today Review / Completed") {
    AppThemeContainer {
        TodayReviewPresenter(
            state: TodayReviewPresenterPreviewData.completedState,
            onClose: {},
            onAdvanceReveal: {},
            onCollapseReveal: {},
            onShuffle: {},
            onPrevious: {},
            onNext: {},
            onForgot: {},
            onRemembered: {},
            onLinkTap: { _ in }
        )
    }
}

private struct PaperFoldModifier: ViewModifier {
    let progress: CGFloat

    func body(content: Content) -> some View {
        content
            .scaleEffect(y: max(progress, 0.02), anchor: .top)
            .rotation3DEffect(
                .degrees(Double((1 - progress) * -88)),
                axis: (x: 1, y: 0, z: 0),
                anchor: .top,
                perspective: 0.86
            )
            .opacity(progress)
            .offset(y: (1 - progress) * -12)
    }
}

private extension AnyTransition {
    static var paperFoldFromTop: AnyTransition {
        .modifier(
            active: PaperFoldModifier(progress: 0),
            identity: PaperFoldModifier(progress: 1)
        )
    }

    static var reviewCardSwap: AnyTransition {
        .asymmetric(
            insertion: .move(edge: .trailing).combined(with: .opacity),
            removal: .scale(scale: 0.985).combined(with: .opacity)
        )
    }
}
