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
    let nextCard: CurrentCard?
    let revealStage: TodayReviewRevealStage
    let canShuffle: Bool
    let canGoPrevious: Bool
    let canGoNext: Bool
    let remainingCount: Int
    let forgotCount: Int
    let rememberedCount: Int
    let rememberedFeedbackTrigger: Int
    let forgotFeedbackTrigger: Int
    let persistenceFailureTrigger: Int
    let persistenceErrorMessage: String?
    let isAdvancing: Bool
}

struct TodayReviewPresenter: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    private var usesCompactLayout: Bool {
        dynamicTypeSize < .accessibility1
    }

    @State private var swipeOffset: CGFloat = 0
    @State private var dismissPhase: DismissPhase = .idle
    @State private var dismissTask: Task<Void, Never>?
    @State private var isPromoting = false
    @State private var stackRotations: [Double] = [
        Double.random(in: -1.0...1.0),
        Double.random(in: -1.0...1.0)
    ]

    /// 卡片退場階段
    private enum DismissPhase {
        case idle
        case animatingOut   // swipe 或按鈕觸發，卡片正在離開畫面
    }

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
                                    .padding(.horizontal, vocabSkin.metrics.reviewCardHorizontalInset)
                                    .padding(.top, vocabSkin.metrics.reviewCardTopInset)
                                    .padding(.bottom, vocabSkin.metrics.reviewCardBottomInset)

                                if state.revealStage == .front {
                                    revealExpandZone(
                                        title: "點一下展開",
                                        minHeight: max(geo.size.height * vocabSkin.metrics.reviewFrontHeightRatio, 180),
                                        action: onAdvanceReveal
                                    )
                                } else if state.revealStage == .back {
                                    revealExpandZone(
                                        title: "點一下查看細節",
                                        minHeight: max(geo.size.height * vocabSkin.metrics.reviewCompletionHeightRatio, 140),
                                        action: onAdvanceReveal
                                    )
                                } else if state.revealStage.showsAnswer {
                                    Spacer(minLength: 0)
                                }
                            }
                            .frame(maxWidth: .infinity, minHeight: geo.size.height, alignment: .top)
                        }
                        .offset(x: swipeOffset * 0.04)
                        .animation(AppMotion.feedbackButtonSpring, value: swipeOffset)
                    }

                    bottomToolbar
                } else {
                    completionState
                }
            }
            .frame(maxWidth: 600)
            .frame(maxWidth: .infinity)
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
        let card = currentCard.card
        return ZStack(alignment: .top) {
            // 牌堆層（微視差跟隨 swipe，在卡片後方）
            cardStackLayers()
                .frame(height: frontCardHeight)

            // 互動卡片（飛出、升頂）
            VStack(spacing: 0) {
                frontFoldSurface(card)

                if state.revealStage.showsAnswer {
                    answerFoldSurface(card)
                        .padding(.top, -1)
                        .transition(.paperFoldFromTop)
                }

                if state.revealStage.showsDetails {
                    detailFoldSheet(currentCard)
                        .padding(.top, -1)
                        .transition(.paperFoldFromTop)
                }
            }
            .scaleEffect(isPromoting ? 0.96 : 1.0)
            .offset(y: isPromoting ? 22 : 0)
            .offset(x: swipeOffset)
            .rotationEffect(.degrees(Double(swipeOffset) / screenWidth * vocabSkin.metrics.reviewSwipeMaxRotation), anchor: .bottom)
            .opacity(cardOpacity)
            .simultaneousGesture(swipeDragGesture)
        }
    }

    /// 卡片當前的 opacity，由 swipeOffset 決定
    private var cardOpacity: Double {
        1.0 - Double(abs(swipeOffset)) / screenWidth * (1.0 - vocabSkin.metrics.reviewSwipeOpacityFloor)
    }

    private var swipeEnabled: Bool {
        state.revealStage.showsAnswer && !state.isAdvancing && dismissPhase == .idle && !isPromoting
    }

    private var screenWidth: CGFloat { UIScreen.main.bounds.width }

    private var swipeDragGesture: some Gesture {
        DragGesture(minimumDistance: 15, coordinateSpace: .local)
            .onChanged { value in
                guard swipeEnabled else { return }
                guard abs(value.translation.width) > abs(value.translation.height) else { return }
                swipeOffset = value.translation.width
            }
            .onEnded { value in
                guard swipeEnabled else { return }
                let threshold = vocabSkin.metrics.reviewSwipeThreshold
                if value.translation.width < -threshold {
                    flingCard(direction: -1, callback: onForgot)
                } else if value.translation.width > threshold {
                    flingCard(direction: 1, callback: onRemembered)
                } else {
                    withAnimation(AppMotion.swipeSnapBackSpring) {
                        swipeOffset = 0
                    }
                }
            }
    }

    /// 統一的卡片甩出動畫 — swipe 和按鈕共用
    /// direction: -1 = 左（忘記）, +1 = 右（記得）
    /// isFromButton: 按鈕觸發時加入蓄力微動
    private func flingCard(direction: CGFloat, isFromButton: Bool = false, callback: @escaping () -> Void) {
        guard dismissPhase == .idle else { return }
        dismissTask?.cancel()
        dismissPhase = .animatingOut

        let flingAnimation = AppMotion.swipeFlingSpring

        dismissTask = Task { @MainActor in
            // 按鈕：蓄力微動（卡片往反方向退 ~8pt）
            if isFromButton {
                withAnimation(.spring(response: 0.1, dampingFraction: 0.9)) {
                    swipeOffset = -direction * 8
                }
                try? await Task.sleep(for: .milliseconds(60))
                guard !Task.isCancelled else { return }
            }

            // 甩出畫面
            withAnimation(.interpolatingSpring(stiffness: 500, damping: 28)) {
                swipeOffset = direction * screenWidth * 1.3
            }
            try? await Task.sleep(for: .milliseconds(100))
            guard !Task.isCancelled else { return }

            // 重置 + 新卡片從牌堆位置出現
            swipeOffset = 0
            isPromoting = true
            stackRotations = [
                Double.random(in: -1.0...1.0),
                Double.random(in: -1.0...1.0)
            ]
            callback()

            // 等 SwiftUI commit 新內容
            try? await Task.sleep(for: .milliseconds(8))
            guard !Task.isCancelled else { return }

            // 新卡片從牌堆升頂，用 reviewRevealSpring 保持 Motion System 一致
            withAnimation(AppMotion.reviewRevealSpring) {
                isPromoting = false
            }

            // 等升頂動畫大致完成後恢復互動
            try? await Task.sleep(for: .milliseconds(150))
            guard !Task.isCancelled else { return }
            dismissPhase = .idle
        }
    }

    // MARK: - 牌堆視覺

    private func cardStackLayers() -> some View {
        ZStack(alignment: .top) {
            // 最底層（第 3 張牌）
            if state.remainingCount >= 2 {
                stackCard(depth: 2)
            }
            // 中間層（第 2 張牌）
            if state.remainingCount >= 1 {
                stackCard(depth: 1)
            }
        }
    }

    private func stackCard(depth: Int) -> some View {
        let baseScale: CGFloat = 1.0 - CGFloat(depth) * 0.025
        let yOffset: CGFloat = CGFloat(depth) * 5
        let rotation = stackRotations[depth - 1]

        // swipe 時第一層微微放大
        let swipeProgress = dismissPhase == .idle
            ? min(abs(swipeOffset) / vocabSkin.metrics.reviewSwipeThreshold, 1.0)
            : 0
        let promoteHint: CGFloat = depth == 1 ? swipeProgress * 0.01 : 0

        return ZStack(alignment: .topLeading) {
            RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                .fill(vocabSkin.palette.cardBackground)
                .overlay(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                        .stroke(vocabSkin.palette.cardBorder.opacity(0.45), lineWidth: 1)
                )
                .shadow(color: vocabSkin.palette.shadow.opacity(0.18), radius: 2, y: 1)

            // depth 1：渲染下一張卡片的正面文字（佈局與 reviewCardFront 一致，避免升頂跳動）
            if depth == 1, let nextCard = state.nextCard {
                VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
                    HStack(spacing: 6) {
                        if let pos = nextCard.card.partOfSpeech {
                            Text(pos)
                                .font(vocabSkin.typography.caption)
                                .foregroundStyle(vocabSkin.palette.quaternaryText)
                        }
                        Spacer()
                    }

                    Spacer(minLength: vocabSkin.metrics.reviewFoldHintBottomInset)

                    Text(nextCard.card.word)
                        .font(reviewFrontWordFont(for: nextCard.card.word))
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                        .lineLimit(2)
                        .minimumScaleFactor(0.7)

                    Spacer(minLength: vocabSkin.metrics.reviewTopBarTopInset)
                }
                .padding(reviewCardPadding)
                .frame(maxWidth: .infinity, alignment: .topLeading)
                .allowsHitTesting(false)
            }
        }
        .frame(height: frontCardHeight)
        .scaleEffect(baseScale + promoteHint)
        .offset(y: yOffset)
        .rotationEffect(.degrees(rotation), anchor: .center)
        .opacity(depth == 1 ? 0.72 : 0.35)
    }

    // MARK: - Swipe 與按鈕連動（方案 A）

    /// swipe 強度 -1（全左）~ 0（靜止）~ +1（全右）
    private var swipeIntensity: Double {
        guard swipeEnabled else { return 0 }
        return max(-1, min(1, Double(swipeOffset / vocabSkin.metrics.reviewSwipeThreshold)))
    }

    /// 忘記按鈕：往左滑時放大+上浮，往右滑時縮小+褪色
    private var forgotButtonScale: CGFloat   { 1.0 + CGFloat(max(-swipeIntensity, 0)) * 0.12 }
    private var forgotButtonOffset: CGFloat  { CGFloat(max(-swipeIntensity, 0)) * -4 }
    private var forgotButtonOpacity: Double  { 1.0 - max(swipeIntensity, 0) * 0.45 }
    private var forgotButtonGlow: Double     { max(-swipeIntensity, 0) }

    /// 記得按鈕：往右滑時放大+上浮，往左滑時縮小+褪色
    private var rememberedButtonScale: CGFloat   { 1.0 + CGFloat(max(swipeIntensity, 0)) * 0.12 }
    private var rememberedButtonOffset: CGFloat  { CGFloat(max(swipeIntensity, 0)) * -4 }
    private var rememberedButtonOpacity: Double  { 1.0 - max(-swipeIntensity, 0) * 0.45 }
    private var rememberedButtonGlow: Double     { max(swipeIntensity, 0) }

    @ViewBuilder
    private func swipeHintView(for offset: CGFloat) -> some View {
        let threshold = vocabSkin.metrics.reviewSwipeThreshold
        let absOffset = abs(offset)
        if absOffset > 20 {
            let intensity = Double(min(absOffset / threshold, 1.0))
            let isForgot = offset < 0
            let color: Color = isForgot ? vocabSkin.palette.destructive : vocabSkin.palette.success
            let label = isForgot ? "忘記" : "記得"
            let rotation: Double = isForgot ? -14 : 14
            let alignment: Alignment = isForgot ? .topLeading : .topTrailing

            Text(label)
                .font(.system(size: 34, weight: .bold, design: .default))
                .foregroundStyle(color)
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .overlay(
                    RoundedRectangle(cornerRadius: 6, style: .continuous)
                        .stroke(color, lineWidth: 2.5)
                )
                .transition(.feedbackBadge)
                .padding(reviewCardPadding)
                .opacity(opacity)
        } else if offset > 10 {
            let opacity = min(Double(offset) / Double(threshold), 1.0)
            Text("記得")
                .font(vocabSkin.typography.captionStrong)
                .foregroundStyle(vocabSkin.palette.success)
                .padding(.horizontal, 14)
                .padding(.vertical, 7)
                .background(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.chip, style: .continuous)
                        .fill(vocabSkin.palette.success.opacity(0.12))
                )
                .transition(.feedbackBadge)
                .padding(reviewCardPadding)
                .opacity(opacity)
                .frame(maxWidth: .infinity, alignment: .trailing)
        }
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
                    .foregroundStyle(vocabSkin.palette.primaryTextMuted)
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
                    truncateAroundMarkedWordRadius: vocabSkin.metrics.exampleTruncateRadius
                )
                .lineSpacing(vocabSkin.metrics.paragraphLineSpacing)
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
            .accessibilityLabel("複習卡片正面：\(card.word)")
            .accessibilityHint(state.revealStage.showsAnswer ? "" : "點一下翻轉卡片")
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
                    .fill(vocabSkin.palette.quaternaryTextFaint)
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

            if usesCompactLayout {
                HStack(spacing: 0) {
                    navButtons
                    Spacer()
                    feedbackButtons
                }
            } else {
                VStack(spacing: vocabSkin.spacing.inlineGap) {
                    feedbackButtons
                        .frame(maxWidth: .infinity)
                    navButtons
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

    private var navButtons: some View {
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
    }

    private var feedbackButtons: some View {
        let spring = Animation.spring(response: 0.22, dampingFraction: 0.72)
        return HStack(spacing: vocabSkin.metrics.sectionHeaderGap) {
            Button { flingCard(direction: -1, isFromButton: true, callback: onForgot) } label: {
                HStack(spacing: 4) {
                    Image(systemName: "xmark")
                    Text("忘記")
                    if state.forgotCount > 0 {
                        Text("·\(state.forgotCount)")
                            .font(vocabSkin.typography.monoLabel)
                    }
                }
                .frame(minWidth: vocabSkin.metrics.reviewActionMinWidth)
            }
            .buttonStyle(.vocabAction(.destructive))
            .disabled(dismissPhase != .idle || !state.revealStage.showsAnswer)
            // 目標方向：放大 + 上浮 + 加深背景
            .overlay(alignment: .center) {
                if forgotButtonGlow > 0 {
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                        .fill(vocabSkin.palette.destructive.opacity(forgotButtonGlow * 0.10))
                        .allowsHitTesting(false)
                }
            }
            .scaleEffect(forgotButtonScale)
            .offset(y: forgotButtonOffset)
            .opacity(forgotButtonOpacity)
            .animation(spring, value: swipeIntensity)

            Button { flingCard(direction: 1, isFromButton: true, callback: onRemembered) } label: {
                HStack(spacing: 4) {
                    Image(systemName: "checkmark")
                    Text("記得")
                    if state.rememberedCount > 0 {
                        Text("·\(state.rememberedCount)")
                            .font(vocabSkin.typography.monoLabel)
                    }
                }
                .frame(minWidth: vocabSkin.metrics.reviewActionMinWidth)
            }
            .buttonStyle(.vocabAction(.success))
            .disabled(dismissPhase != .idle || !state.revealStage.showsAnswer)
            // 目標方向：放大 + 上浮 + 加深背景
            .overlay(alignment: .center) {
                if rememberedButtonGlow > 0 {
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                        .fill(vocabSkin.palette.success.opacity(rememberedButtonGlow * 0.10))
                        .allowsHitTesting(false)
                }
            }
            .scaleEffect(rememberedButtonScale)
            .offset(y: rememberedButtonOffset)
            .opacity(rememberedButtonOpacity)
            .animation(spring, value: swipeIntensity)
        }
    }

    private var completionState: some View {
        VStack(spacing: vocabSkin.metrics.cardBlockPadding) {
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
        .padding(.horizontal, vocabSkin.metrics.cardBlockPadding)
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
        let answerText = card.reviewMode == .production ? card.word : card.translation
        return foldSurface(position: state.revealStage.showsDetails ? .middle : .bottom) {
            ZStack(alignment: .topTrailing) {
                if state.revealStage == .back {
                    Button(action: onAdvanceReveal) {
                        answerFoldContent(card, showsExpandHint: true)
                    }
                    .buttonStyle(.plain)
                    .contentShape(Rectangle())
                    .accessibilityLabel("翻譯：\(answerText)")
                    .accessibilityHint("點一下查看細節")
                } else {
                    answerFoldContent(card, showsExpandHint: false)
                        .accessibilityLabel("翻譯：\(answerText)")
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

            let meaningParagraphs = answerMeaningParagraphs(for: card)
            if !meaningParagraphs.isEmpty {
                CardSectionDivider(horizontalPadding: 0)
                VStack(alignment: .leading, spacing: vocabSkin.metrics.cardBlockContentGap) {
                    ForEach(meaningParagraphs) { paragraph in
                        CardInlineText(paragraph: paragraph, style: .body)
                            .lineSpacing(5)
                    }
                }
            }

            Spacer(minLength: 0)
        }
        .padding(reviewCardPadding)
        .padding(.trailing, showsExpandHint ? 40 : 0)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .frame(minHeight: answerCardHeight, alignment: .topLeading)
    }

    private func answerMeaningParagraphs(for card: CardPresentation) -> [CardDocumentParagraph] {
        for block in card.document.blocks {
            if case .meaning(let meaning) = block {
                return meaning.paragraphs
            }
        }
        return []
    }

    private func detailFoldSheet(_ currentCard: TodayReviewPresenterState.CurrentCard) -> some View {
        let card = currentCard.card
        return foldSurface(position: .bottom) {
            VStack(alignment: .leading, spacing: vocabSkin.metrics.reviewFoldSectionSpacing) {
                HStack {
                    Spacer()
                    foldChevronButton(action: onCollapseReveal)
                }

                CardDocumentView(document: reviewBackDocument(for: card), truncateRadius: 5)

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
            .shadow(color: vocabSkin.palette.shadow.opacity(position == .single ? 1 : AppShadows.panelOpacity), radius: 6, y: AppShadows.coverY)
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
        // 僅保留例句和來源，排除 meaning 及其前方 divider
        var blocks: [CardDocumentBlock] = []
        var pendingDivider = false
        for block in card.document.blocks {
            switch block {
            case .hero, .meaning:
                pendingDivider = false
            case .divider:
                pendingDivider = true
            case .example, .source:
                if pendingDivider && !blocks.isEmpty {
                    blocks.append(.divider)
                }
                blocks.append(block)
                pendingDivider = false
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

    static let nextCard = TodayReviewPresenterState.CurrentCard(
        card: {
            let entry = VocabularyEntry(
                word: "ephemeral",
                translation: "短暫的；轉瞬即逝的",
                context: "Social media posts are ephemeral by nature.",
                explanation: "形容事物存在時間極短。",
                partOfSpeech: "adj.",
                pronunciation: "ɪˈfemərəl",
                bookTitle: "Designing Interfaces",
                chapterTitle: "Writing Tone"
            )
            entry.dateAdded = Date(timeIntervalSince1970: 1_736_001_000)
            entry.reviewMode = .recognition
            return entry.cardPresentation
        }(),
        linkGroups: []
    )

    static func state(stage: TodayReviewRevealStage) -> TodayReviewPresenterState {
        .init(
            progressText: "3 / 12",
            currentCard: currentCard,
            nextCard: nextCard,
            revealStage: stage,
            canShuffle: true,
            canGoPrevious: true,
            canGoNext: true,
            remainingCount: 9,
            forgotCount: 1,
            rememberedCount: 2,
            rememberedFeedbackTrigger: 0,
            forgotFeedbackTrigger: 0,
            persistenceFailureTrigger: 0,
            persistenceErrorMessage: nil,
            isAdvancing: false
        )
    }

    static let completedState = TodayReviewPresenterState(
        progressText: "12 / 12",
        currentCard: nil,
        nextCard: nil,
        revealStage: .front,
        canShuffle: false,
        canGoPrevious: false,
        canGoNext: false,
        remainingCount: 0,
        forgotCount: 4,
        rememberedCount: 8,
        rememberedFeedbackTrigger: 0,
        forgotFeedbackTrigger: 0,
        persistenceFailureTrigger: 0,
        persistenceErrorMessage: nil,
        isAdvancing: false
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

#Preview("Today Review / Back") {
    AppThemeContainer {
        TodayReviewPresenter(
            state: TodayReviewPresenterPreviewData.state(stage: .back),
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
}
