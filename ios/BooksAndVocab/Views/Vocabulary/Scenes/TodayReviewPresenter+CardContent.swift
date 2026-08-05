import SwiftUI

// MARK: - Card Content Rendering

extension TodayReviewPresenter {

    // MARK: Dimensions

    var reviewCardPadding: CGFloat { TodayReviewMetrics.foldPadding }
    var answerCardHeight: CGFloat { TodayReviewMetrics.answerMinHeight }

    /// 右上角 chrome（喇叭 + 詳情）兩顆 44pt HIG 觸控框 + 中間 inlineGap 的總寬，
    /// 供單字列保留 trailing 空間，避免長詞被圖示擋住。與 frontCardChrome 佈局同源。
    var frontChromeReserveWidth: CGFloat { 44 * 2 + appSkin.spacing.inlineGap }

    // MARK: Front Surface

    /// 卡正面摺頁面。Phase 3a 起由常駐 slot 呼叫：`showsAnswer` / `interactive`
    /// 是 per-slot 投影值（preview slot 恆 false），`borderOpacity` 由
    /// `TodayReviewCardSlotLayout.borderOpacity` 內插（0.45 → 0.72），promote
    /// 翻面時邊框零 pop。`todayReview.card.front` a11y 識別子只掛在 active slot。
    func frontFoldSurface(
        _ currentCard: TodayReviewPresenterState.CurrentCard,
        showsAnswer: Bool,
        interactive: Bool,
        borderOpacity: Double,
        viewport: ReviewCardViewport
    ) -> some View {
        let card = currentCard.card
        let layout = reviewCardLayout(for: currentCard, face: .front, availableHeight: viewport.frontHeight)
        let _ = PerfLog.render.tick("todayReview.front.surface", "mode=\(card.reviewMode.rawValue)")
        if interactive, let clock = TodayReviewState.flingClock {
            PerfLog.review.mark("front.gap", "w=\(card.word) \(PerfChannel.ms(since: clock))ms (fling->current-front body)")
            TodayReviewState.flingClock = nil
        }
        return ReviewFoldSurface(
            position: showsAnswer ? .top : .single,
            borderOpacity: borderOpacity
        ) {
            frontFaceContent(
                currentCard,
                layout: layout,
                viewport: viewport,
                measuresSections: interactive
            )
            .frame(maxWidth: .infinity, alignment: .topLeading)
            .frame(minHeight: layout.cardHeight, alignment: .topLeading)
            .contentShape(Rectangle())
            .onTapGesture {
                guard !showsAnswer, interactive, isCardInteractive else { return }
                onAdvanceReveal()
            }
            .accessibilityIdentifier(interactive ? "todayReview.card.front" : "")
            .accessibilityLabel(L10n.format("複習卡片正面：%@", card.word))
            .accessibilityHint(showsAnswer || !interactive ? "" : "點一下翻轉卡片".localized)
            .accessibilityAction {
                guard !showsAnswer, interactive, isCardInteractive else { return }
                onAdvanceReveal()
            }
        }
    }

    @ViewBuilder
    private func frontFaceContent(
        _ currentCard: TodayReviewPresenterState.CurrentCard,
        layout: ReviewCardLayoutSolver.Result,
        viewport: ReviewCardViewport,
        measuresSections: Bool
    ) -> some View {
        // Same number the solver was handed — the clamp and the budget are one value.
        let maxHeight = max(viewport.frontHeight, 1)
        if layout.requiresScrollFallback {
            ScrollView(.vertical) {
                reviewCardFront(currentCard, layout: layout, measuresSections: measuresSections)
            }
                .frame(maxHeight: maxHeight)
        } else {
            ViewThatFits(in: .vertical) {
                reviewCardFront(currentCard, layout: layout, measuresSections: measuresSections)
                    .fixedSize(horizontal: false, vertical: true)
                ScrollView(.vertical) {
                    reviewCardFront(currentCard, layout: layout, measuresSections: measuresSections)
                }
            }
            .frame(maxHeight: maxHeight)
        }
    }

    /// 卡片右上角 chrome（喇叭 / 詳情）。作用中卡片與背後 deck 預覽**共用同一渲染**，
    /// 確保 fling 飛出期間背後預覽已帶完整 chrome、完成時的 swap 隱形（消除「裸卡 pop」）。
    /// `interactive=false`（預覽）時純裝飾：無動作、不可點。
    @ViewBuilder
    func frontCardChrome(_ card: CardPresentation, interactive: Bool) -> some View {
        let _ = { if interactive, dismissPhase != .idle || swipeOffset != 0 {
            PerfLog.review.mark("front.chrome", "w=\(card.word) (active card chrome rendered)")
        } }()
        HStack(spacing: appSkin.spacing.inlineGap) {
            VocabChromeIconButton(
                systemImage: "speaker.wave.2.fill",
                label: "播放發音".localized,
                action: { if interactive { speechService.speak(card.word) } }
            )
            VocabChromeIconButton(
                systemImage: "arrow.up.right",
                label: "查看詳情".localized,
                action: { if interactive, isCardInteractive { onDetailTap() } }
            )
        }
        .padding(reviewCardPadding)
        .allowsHitTesting(interactive)
    }

    func reviewCardFront(
        _ currentCard: TodayReviewPresenterState.CurrentCard,
        layout: ReviewCardLayoutSolver.Result,
        measuresSections: Bool
    ) -> some View {
        let card = currentCard.card
        let plan = reviewCardRenderPlan(for: currentCard)
        let _ = PerfLog.review.mark("front.body", "w=\(card.word) reveal=\(state.revealStage)")
        // Spacing comes from the solver's own arithmetic, never re-derived here.
        return VStack(alignment: .leading, spacing: layout.sectionSpacing) {
            HStack(alignment: .firstTextBaseline, spacing: AppSpacing.s2) {
                switch card.reviewMode {
                case .recognition:
                    Text(card.word)
                        .font(reviewFrontWordFont(for: card.word))
                        .foregroundStyle(appSkin.palette.primaryText)
                        .lineLimit(3)
                        .minimumScaleFactor(0.7)
                        .fixedSize(horizontal: false, vertical: true)
                case .production:
                    Text(card.translation)
                        .font(appSkin.typography.body.weight(.semibold))
                        .foregroundStyle(appSkin.palette.primaryTextMuted)
                        .minimumScaleFactor(0.75)
                }

            }
            // 右上角 chrome（喇叭 / 詳情）是 overlay（必須在 reveal Button 外才能獨立點），
            // 故在單字列保留其寬度的 trailing 空間，長詞（如 "be eaten alive"）在碰到
            // 圖示前先縮放 / 換行，不被擋字。
            .padding(.trailing, frontChromeReserveWidth)
            .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { height in
                recordReviewSectionHeight(
                    height,
                    currentCard: currentCard,
                    face: .front,
                    section: .core,
                    level: .natural
                )
            }

            ForEach(plan.front.fields, id: \.self) { field in
                reviewOptionalField(
                    field,
                    currentCard: currentCard,
                    face: .front,
                    policy: layout.policy(for: .field(field))
                )
                    .background {
                        if measuresSections {
                            reviewMeasurementProbes(
                                field,
                                currentCard: currentCard,
                                face: .front
                            )
                        }
                    }
                    .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { height in
                        recordReviewSectionHeight(
                            height,
                            currentCard: currentCard,
                            face: .front,
                            section: .field(field),
                            level: layout.policy(for: .field(field)).measurementLevel
                        )
                    }
            }
        }
        .reviewCardFaceChrome(.front)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .frame(minHeight: layout.cardHeight, alignment: .topLeading)
    }

    // MARK: Combined Answer Surface

    /// 答案摺頁面。`mounted` 是 per-slot 投影（active slot 才掛
    /// `backContentMounted` 閘；preview slot 恆 stub）— 閘語意不變，見
    /// TodayReviewPresenter.updateBackContentMount。
    func answerFoldSurface(
        _ currentCard: TodayReviewPresenterState.CurrentCard,
        viewport: ReviewCardViewport,
        mounted: Bool
    ) -> some View {
        let card = currentCard.card
        let answerText = card.reviewMode == .production ? card.word : card.translation
        return ReviewFoldSurface(position: .bottom) {
            // Subtraction probe: while the FRONT card is shown the back tree
            // (CardDocumentView / CardRichTextRenderer / VocabTierLabel /
            // reviewLinkStrip) is NOT built — only a zero-cost stub holds the
            // folded slot. Mount is gated by `backContentMounted`, NOT `showsAnswer`:
            // on reveal it mounts under the opening fold's opacity-0 cover; on
            // collapse it STAYS mounted until the PaperFoldModifier progress 1→0
            // finishes, so the fold folds the REAL content (not an empty box).
            // See TodayReviewPresenter.updateBackContentMount for the falling-edge
            // defer + generation guard.
            // stub 用 answerCardHeight 撐 minHeight，與真內容同源，
            // 避免折疊→展開時 intrinsic 高度跳動。
            Group {
                if mounted {
                    // Identifier on the MOUNTED branch only: UI tests read
                    // `todayReview.card.back`.exists as the real flip-state
                    // signal (the folded stub deliberately carries none).
                    combinedAnswerContent(currentCard, viewport: viewport)
                        .accessibilityIdentifier("todayReview.card.back")
                } else {
                    let _ = PerfLog.review.mark("back.stub", "w=\(card.word)")
                    Color.clear
                        .frame(maxWidth: .infinity, minHeight: answerCardHeight, alignment: .top)
                }
            }
            .accessibilityLabel(L10n.format("翻譯：%@", answerText))
        }
        .overlay(alignment: .top) {
            ReviewFoldChevronPill(action: onCollapseReveal, accessibilityLabel: L10n.string("todayReview.fold.collapse"))
                .offset(y: -TodayReviewMetrics.chevronButtonSize / 2)
        }
    }

    func combinedAnswerContent(_ currentCard: TodayReviewPresenterState.CurrentCard, viewport: ReviewCardViewport) -> some View {
        let card = currentCard.card
        let _ = PerfLog.render.tick(
            "todayReview.answer.surface",
            "mode=\(card.reviewMode.rawValue) blocks=\(currentCard.backDocument.blocks.count)"
        )
        let plan = reviewCardRenderPlan(for: currentCard)
        // The outer insets are already out of `contentHeight`, so the front's
        // measured height is the only thing left to subtract — counting the insets
        // twice was the other half of the disagreeing-budget defect.
        let backAvailableHeight = viewport.backHeight(
            frontOccupied: activeCardHeight + TodayReviewMetrics.stackLayerMicroOffset
        )
        let layout = reviewCardLayout(for: currentCard, face: .back, availableHeight: backAvailableHeight)
        let maxHeight = max(backAvailableHeight, 1)
        return Group {
            if layout.requiresScrollFallback {
                ScrollView(.vertical) { answerContent(currentCard, plan: plan, layout: layout) }
                    .frame(maxHeight: maxHeight)
            } else {
                ViewThatFits(in: .vertical) {
                    answerContent(currentCard, plan: plan, layout: layout)
                        .fixedSize(horizontal: false, vertical: true)
                    ScrollView(.vertical) { answerContent(currentCard, plan: plan, layout: layout) }
                }
                .frame(maxHeight: maxHeight)
            }
        }
    }

    @ViewBuilder
    private func answerContent(
        _ currentCard: TodayReviewPresenterState.CurrentCard,
        plan: ReviewCardRenderPlan,
        layout: ReviewCardLayoutSolver.Result
    ) -> some View {
        let card = currentCard.card
        // Same rule as the front face: draw the gap the solver charged.
        VStack(alignment: .leading, spacing: layout.sectionSpacing) {

            // Answer word + its section rule form ONE core section: the rule is the
            // core's own chrome (as on the shipped card), so it is measured with the
            // core rather than competing with the profile's fields for a slot.
            VStack(alignment: .leading, spacing: layout.sectionSpacing) {
                Group {
                    if card.reviewMode == .production {
                        Text(card.word)
                    } else {
                        Text(card.translation)
                    }
                }
                .font(reviewAnswerWordFont(for: card.reviewMode == .production ? card.word : card.translation))
                .foregroundStyle(appSkin.palette.primaryText)
                .lineLimit(3)
                .minimumScaleFactor(0.65)
                .fixedSize(horizontal: false, vertical: true)

                if ReviewCardLayoutSolver.drawsAnswerDivider(fields: plan.back.fields) {
                    CardSectionDivider(horizontalPadding: 0)
                }
            }
            .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { height in
                recordReviewSectionHeight(
                    height,
                    currentCard: currentCard,
                    face: .back,
                    section: .core,
                    level: .natural
                )
            }

            ForEach(plan.back.fields, id: \.self) { field in
                reviewOptionalField(
                    field,
                    currentCard: currentCard,
                    face: .back,
                    policy: layout.policy(for: .field(field))
                )
                    .background {
                        reviewMeasurementProbes(
                            field,
                            currentCard: currentCard,
                            face: .back
                        )
                    }
                    .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { height in
                        recordReviewSectionHeight(
                            height,
                            currentCard: currentCard,
                            face: .back,
                            section: .field(field),
                            level: layout.policy(for: .field(field)).measurementLevel
                        )
                    }
            }
        }
        .reviewCardFaceChrome(.back)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .frame(minHeight: layout.cardHeight, alignment: .topLeading)
    }

    // MARK: Link Strip

    func reviewLinkStrip(
        _ groups: [TodayReviewPresenterState.LinkGroup],
        presentation: ReviewCardLayoutSolver.GraphLinkPresentation = .twoPerGroup
    ) -> some View {
        HStack(alignment: .top, spacing: appSkin.spacing.inlineGap) {
            Image(systemName: "paperclip")
                .font(appSkin.typography.iconTiny)
                .foregroundStyle(appSkin.palette.tertiaryText)
                .padding(.top, TodayReviewMetrics.answerHintTopPadding)

            VStack(alignment: .leading, spacing: appSkin.spacing.inlineGap) {
                ForEach(groups) { group in
                    HStack(spacing: AppSpacing.s1) {
                        Text(group.label.localized + "：")
                            .font(appSkin.typography.caption)
                            .foregroundStyle(appSkin.palette.tertiaryText)

                        let shownItems: [KGCardLinkSummary] = {
                            switch presentation {
                            case .twoPerGroup: Array(group.items.prefix(2))
                            case .onePerGroup: Array(group.items.prefix(1))
                            case .summary: []
                            }
                        }()
                        ForEach(Array(shownItems.enumerated()), id: \.element.id) { index, item in
                            Button { onLinkTap(item) } label: {
                                Text(item.word)
                                    .font(appSkin.typography.monoEmphasis)
                                    .foregroundStyle(appSkin.palette.primaryText)
                            }
                            .buttonStyle(.plain)

                            if index < shownItems.count - 1 {
                                Text("|")
                                    .font(appSkin.typography.caption)
                                    .foregroundStyle(appSkin.palette.quaternaryText)
                            }
                        }

                        let overflow = group.overflowCount + max(group.items.count - shownItems.count, 0)
                        if overflow > 0 {
                            Text("+\(overflow)")
                                .font(appSkin.typography.caption)
                                .foregroundStyle(appSkin.palette.quaternaryText)
                        }
                    }
                }
            }

            Spacer()

            Button(action: onAddLink) {
                Image(systemName: "plus")
                    .font(appSkin.typography.iconSmall)
                    .foregroundStyle(appSkin.palette.secondaryText)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(L10n.string("vocab.card.addLink"))
            .accessibilityIdentifier("todayReview.card.addLink")
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// Shown by the graph-links section when the card has no links yet. It is the
    /// only place the review card can create its first link, which is why the
    /// section is always *available* even though its content is empty.
    private var addLinkPrompt: some View {
        Button(action: onAddLink) {
            HStack(spacing: appSkin.spacing.inlineGap) {
                Image(systemName: "plus")
                    .font(appSkin.typography.iconTiny)
                Text("新增連結".localized)
                    .font(appSkin.typography.caption)
            }
            .foregroundStyle(appSkin.palette.tertiaryText)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("todayReview.card.addLink")
    }

    // MARK: - Render Plan / Adaptive Layout

    private func reviewCardRenderPlan(
        for currentCard: TodayReviewPresenterState.CurrentCard
    ) -> ReviewCardRenderPlan {
        let card = currentCard.card
        return .make(
            profile: reviewCardLayoutStore.profile,
            mode: card.reviewMode,
            availability: .forReviewCard(
                partOfSpeech: card.partOfSpeech,
                difficultyTier: card.difficultyTier,
                exampleCount: card.examples.count,
                explanationParagraphCount: currentCard.backDocument.meaningParagraphs().count,
                collocationCount: card.collocations.count
            )
        )
    }

    private func reviewCardLayout(
        for currentCard: TodayReviewPresenterState.CurrentCard,
        face: ReviewCardFace,
        availableHeight: CGFloat
    ) -> ReviewCardLayoutSolver.Result {
        let plan = reviewCardRenderPlan(for: currentCard)
        let fields = face == .front ? plan.front.fields : plan.back.fields
        let defaults: [ReviewCardLayoutSolver.Section: ReviewCardLayoutSolver.Measurement] = [
            .core: .init(naturalHeight: face == .front ? 112 : 132),
            .field(.partOfSpeech): .init(naturalHeight: 22),
            .field(.difficultyTier): .init(naturalHeight: 24),
            .field(.example): .init(naturalHeight: 88, compactHeight: 44),
            .field(.explanation): .init(naturalHeight: 66, intermediateHeight: 44, compactHeight: 22),
            .field(.collocations): .init(naturalHeight: 64, intermediateHeight: 48, compactHeight: 32),
            .field(.graphLinks): .init(naturalHeight: 72, intermediateHeight: 48, compactHeight: 20)
        ]
        let sections = [ReviewCardLayoutSolver.Section.core] + fields.map(ReviewCardLayoutSolver.Section.field)
        let measurements = Dictionary(uniqueKeysWithValues: sections.map { section in
            let key = reviewMeasurementKey(for: currentCard, face: face, section: section)
            let fallback = defaults[section] ?? .init(naturalHeight: 0)
            return (section, ReviewCardLayoutSolver.Measurement(
                naturalHeight: reviewNaturalSectionHeights[key] ?? fallback.naturalHeight,
                intermediateHeight: reviewIntermediateSectionHeights[key] ?? fallback.intermediateHeight,
                compactHeight: reviewCompactSectionHeights[key] ?? fallback.compactHeight
            ))
        })
        return ReviewCardLayoutSolver.solve(.init(
            face: face,
            fields: fields,
            measurements: measurements,
            viewportHeight: availableHeight,
            minimumHeight: face == .front ? 0 : answerCardHeight
        ))
    }

    private func reviewMeasurementKey(
        for currentCard: TodayReviewPresenterState.CurrentCard,
        face: ReviewCardFace,
        section: ReviewCardLayoutSolver.Section
    ) -> ReviewCardMeasurementKey {
        ReviewCardMeasurementKey(
            cardKey: "\(currentCard.card.dateAdded.timeIntervalSinceReferenceDate)-\(currentCard.card.word)",
            face: face,
            section: section,
            widthBucket: Int(containerWidth.rounded()),
            dynamicType: String(describing: dynamicTypeSize)
        )
    }

    private func recordReviewSectionHeight(
        _ height: CGFloat,
        currentCard: TodayReviewPresenterState.CurrentCard,
        face: ReviewCardFace,
        section: ReviewCardLayoutSolver.Section,
        level: ReviewCardLayoutSolver.MeasurementLevel
    ) {
        guard height > 0 else { return }
        let key = reviewMeasurementKey(for: currentCard, face: face, section: section)
        switch level {
        case .natural:
            guard abs((reviewNaturalSectionHeights[key] ?? 0) - height) > 0.5 else { return }
            reviewNaturalSectionHeights[key] = height
        case .intermediate:
            guard abs((reviewIntermediateSectionHeights[key] ?? 0) - height) > 0.5 else { return }
            reviewIntermediateSectionHeights[key] = height
        case .compact:
            guard abs((reviewCompactSectionHeights[key] ?? 0) - height) > 0.5 else { return }
            reviewCompactSectionHeights[key] = height
        }
    }

    @ViewBuilder
    private func reviewMeasurementProbes(
        _ field: ReviewCardField,
        currentCard: TodayReviewPresenterState.CurrentCard,
        face: ReviewCardFace
    ) -> some View {
        let key = reviewMeasurementKey(for: currentCard, face: face, section: .field(field))
        let levels = ReviewCardLayoutSolver.missingMeasurementLevels(
            hasNatural: reviewNaturalSectionHeights[key] != nil,
            hasIntermediate: reviewIntermediateSectionHeights[key] != nil,
            hasCompact: reviewCompactSectionHeights[key] != nil
        )
        ZStack(alignment: .topLeading) {
            ForEach(levels, id: \.self) { level in
                reviewOptionalField(
                    field,
                    currentCard: currentCard,
                    face: face,
                    policy: .measurementProbe(for: field, level: level)
                )
                .fixedSize(horizontal: false, vertical: true)
                .hidden()
                .allowsHitTesting(false)
                .accessibilityHidden(true)
                .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { height in
                    recordReviewSectionHeight(
                        height,
                        currentCard: currentCard,
                        face: face,
                        section: .field(field),
                        level: level
                    )
                }
            }
        }
    }

    @ViewBuilder
    private func reviewOptionalField(
        _ field: ReviewCardField,
        currentCard: TodayReviewPresenterState.CurrentCard,
        face: ReviewCardFace,
        policy: ReviewCardLayoutSolver.Policy
    ) -> some View {
        let card = currentCard.card
        switch field {
        case .partOfSpeech:
            if let partOfSpeech = card.partOfSpeech {
                Text(partOfSpeech)
                    .font(appSkin.typography.body)
                    .foregroundStyle(appSkin.palette.tertiaryText)
            }
        case .difficultyTier:
            // Trailing-aligned, as the tier pill has always hugged the card's edge.
            if let tier = card.difficultyTier {
                VocabTierLabel(tier: tier)
                    .frame(maxWidth: .infinity, alignment: .trailing)
            }
        case .example:
            if let example = card.examples.first {
                CardRichTextRenderer.text(
                    example,
                    style: CardRichTextStyle(
                        font: appSkin.typography.example,
                        textColor: appSkin.palette.secondaryText,
                        highlightColor: appSkin.palette.highlightMark,
                        italic: true,
                        underlineHighlights: appSkin.highlight.showUnderline,
                        useBackgroundMark: appSkin.highlight.showBackground,
                        highlightWeight: appSkin.highlight.fontWeight,
                        backgroundOpacity: appSkin.highlight.backgroundOpacity,
                        underlineOpacity: appSkin.highlight.underlineOpacity
                    ),
                    mode: .cloze,
                    truncateAroundMarkedWordRadius: policy.exampleRadius
                        ?? ReviewCardLayoutSolver.naturalExampleRadius(
                            for: face,
                            staticRadius: appSkin.metrics.exampleTruncateRadius
                        ),
                    targetWord: card.word
                )
                .lineSpacing(appSkin.metrics.paragraphLineSpacing)
            }
        case .explanation:
            // One globally-limited rich text rather than per-paragraph clamps: the
            // solver budgets one section, so one clamp must own the whole block.
            // Natural is the shipped 3-line / 5pt compact meaning presentation.
            CardRichTextRenderer.text(
                ReviewCardExplanationContent.rawMarkdown(
                    from: currentCard.backDocument.meaningParagraphs()
                ),
                style: CardRichTextStyle(
                    font: appSkin.typography.body,
                    textColor: appSkin.palette.secondaryText,
                    highlightColor: appSkin.palette.highlightMark,
                    italic: false,
                    underlineHighlights: false,
                    useBackgroundMark: false,
                    highlightWeight: appSkin.highlight.fontWeight,
                    backgroundOpacity: appSkin.highlight.backgroundOpacity,
                    underlineOpacity: appSkin.highlight.underlineOpacity
                )
            )
            .lineSpacing(TodayReviewMetrics.foldMeaningLineSpacing)
            .lineLimit(ReviewCardLayoutSolver.explanationLineLimit(policyLineLimit: policy.lineLimit))
            .fixedSize(horizontal: false, vertical: true)
        case .collocations:
            let visible: [String] = if let limit = ReviewCardLayoutSolver.visibleCollocationLimit(
                lineLimit: policy.lineLimit
            ) {
                Array(card.collocations.prefix(limit))
            } else {
                card.collocations
            }
            VStack(alignment: .leading, spacing: appSkin.spacing.inlineGap) {
                CardDocumentCollocationsBlock(
                    items: visible,
                    compact: true,
                    maxRows: ReviewCardLayoutSolver.collocationRowLimit(lineLimit: policy.lineLimit),
                    explanations: collocationExplanations,
                    onExplain: onExplainCollocation,
                    onView: onViewCollocationExplanation,
                    onDelete: onDeleteCollocationExplanation
                )
                if policy.summarizesOverflow, card.collocations.count > visible.count {
                    Text("+\(card.collocations.count - visible.count)")
                        .font(appSkin.typography.caption)
                        .foregroundStyle(appSkin.palette.tertiaryText)
                }
            }
        case .graphLinks:
            // No links yet → the add-link prompt, never nothing: this is the only
            // place the review card can start a link from.
            if currentCard.linkGroups.isEmpty {
                addLinkPrompt
            } else {
                reviewLinkStrip(currentCard.linkGroups, presentation: policy.graphLinkPresentation ?? .twoPerGroup)
            }
        }
    }

    // MARK: Fonts

    func reviewFrontWordFont(for text: String) -> Font {
        let count = text.count
        if count > 20 { return AppFonts.systemMono(size: TodayReviewMetrics.counterFontSizeCompact, weight: .semibold) }
        if count > 12 { return AppFonts.systemMono(size: TodayReviewMetrics.counterFontSizeMedium, weight: .semibold) }
        return AppFonts.systemMono(size: TodayReviewMetrics.counterFontSizeXLarge, weight: .semibold)
    }

    func reviewAnswerWordFont(for text: String) -> Font {
        let count = text.count
        if count > 20 { return appSkin.typography.translationTitle }
        if count > 12 { return AppFonts.systemMono(size: TodayReviewMetrics.counterFontSizeLarge, weight: .semibold) }
        return appSkin.typography.reviewWord
    }

}

// MARK: - Face Chrome

extension View {
    /// The only place a review card face pads its content. `ReviewCardChrome` hands
    /// the identical numbers to the solver as `chromeHeight`, so the budget and the
    /// drawn inset move together or not at all.
    func reviewCardFaceChrome(_ face: ReviewCardFace) -> some View {
        padding(ReviewCardChrome.padding)
            .padding(.top, ReviewCardChrome.extraTopInset(for: face))
    }
}
