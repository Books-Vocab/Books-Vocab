import SwiftUI

// MARK: - Card Content Rendering

extension TodayReviewPresenter {

    // MARK: Dimensions

    var reviewCardPadding: CGFloat { TodayReviewMetrics.foldPadding }
    var frontCardHeight: CGFloat { TodayReviewMetrics.frontMinHeight }
    var answerCardHeight: CGFloat { TodayReviewMetrics.answerMinHeight }

    /// 右上角 chrome（喇叭 + 詳情）兩顆 44pt HIG 觸控框 + 中間 inlineGap 的總寬，
    /// 供單字列保留 trailing 空間，避免長詞被圖示擋住。與 frontCardChrome 佈局同源。
    var frontChromeReserveWidth: CGFloat { 44 * 2 + appSkin.spacing.inlineGap }

    // MARK: Front Surface

    func frontFoldSurface(_ card: CardPresentation) -> some View {
        let _ = PerfLog.render.tick("todayReview.front.surface", "mode=\(card.reviewMode.rawValue)")
        if let clock = TodayReviewState.flingClock {
            PerfLog.review.mark("front.gap", "w=\(card.word) \(PerfChannel.ms(since: clock))ms (fling->current-front body)")
            TodayReviewState.flingClock = nil
        }
        return ReviewFoldSurface(position: state.revealStage.showsAnswer ? .top : .single) {
            Button(action: onAdvanceReveal) {
                reviewCardFront(card)
                    .frame(maxWidth: .infinity, alignment: .topLeading)
                    .frame(minHeight: frontCardHeight, alignment: .topLeading)
            }
            .buttonStyle(.plain)
            .frame(maxWidth: .infinity, alignment: .topLeading)
            .frame(minHeight: frontCardHeight, alignment: .topLeading)
            .contentShape(Rectangle())
            .disabled(state.revealStage.showsAnswer || !isCardInteractive)
            .accessibilityLabel(L10n.format("複習卡片正面：%@", card.word))
            .accessibilityHint(state.revealStage.showsAnswer ? "" : "點一下翻轉卡片".localized)
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

    func reviewCardFront(_ card: CardPresentation) -> some View {
        let _ = PerfLog.review.mark("front.body", "w=\(card.word) reveal=\(state.revealStage)")
        return VStack(alignment: .leading, spacing: TodayReviewMetrics.foldSectionSpacing) {
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

                if let pos = card.partOfSpeech {
                    Text(pos)
                        .font(appSkin.typography.body)
                        .foregroundStyle(appSkin.palette.tertiaryText)
                }
            }
            // 右上角 chrome（喇叭 / 詳情）是 overlay（必須在 reveal Button 外才能獨立點），
            // 故在單字列保留其寬度的 trailing 空間，長詞（如 "be eaten alive"）在碰到
            // 圖示前先縮放 / 換行，不被擋字。
            .padding(.trailing, frontChromeReserveWidth)

            if card.reviewMode == .production, let example = card.examples.first {
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
                    truncateAroundMarkedWordRadius: appSkin.metrics.exampleTruncateRadius,
                    targetWord: card.word
                )
                .lineSpacing(appSkin.metrics.paragraphLineSpacing)
            }
        }
        .padding(reviewCardPadding)
        .padding(.top, TodayReviewMetrics.foldHintBottomInset)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .frame(minHeight: frontCardHeight, alignment: .topLeading)
    }

    // MARK: Combined Answer Surface

    func answerFoldSurface(_ currentCard: TodayReviewPresenterState.CurrentCard, availableHeight: CGFloat) -> some View {
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
            // stub 用 answerCardHeight 撐 minHeight，與真內容 :191 同源，
            // 避免折疊→展開時 intrinsic 高度跳動。
            Group {
                if backContentMounted {
                    combinedAnswerContent(currentCard, availableHeight: availableHeight)
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

    func combinedAnswerContent(_ currentCard: TodayReviewPresenterState.CurrentCard, availableHeight: CGFloat) -> some View {
        let card = currentCard.card
        let _ = PerfLog.render.tick(
            "todayReview.answer.surface",
            "mode=\(card.reviewMode.rawValue) blocks=\(currentCard.backDocument.blocks.count)"
        )
        let hasLinks = !currentCard.linkGroups.isEmpty
        let exampleRadius = answerExampleRadius(
            containerHeight: availableHeight,
            currentCard: currentCard
        )
        return VStack(alignment: .leading, spacing: TodayReviewMetrics.foldSectionSpacing) {
            HStack(spacing: 6) {
                Spacer()
                if let tier = card.difficultyTier {
                    VocabTierLabel(tier: tier)
                }
            }

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

            CardSectionDivider(horizontalPadding: 0)
            if hasLinks {
                reviewLinkStrip(currentCard.linkGroups)
            } else {
                addLinkPrompt
            }

            if !currentCard.backDocument.blocks.isEmpty {
                CardDocumentView(
                    document: currentCard.backDocument,
                    truncateRadius: exampleRadius,
                    targetWord: card.word,
                    compact: true,
                    collocationExplanations: collocationExplanations,
                    onExplainCollocation: onExplainCollocation,
                    onViewCollocationExplanation: onViewCollocationExplanation,
                    onDeleteCollocationExplanation: onDeleteCollocationExplanation
                )
            }
        }
        .padding(reviewCardPadding)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .frame(minHeight: answerCardHeight, alignment: .topLeading)
    }

    // MARK: Link Strip

    func reviewLinkStrip(_ groups: [TodayReviewPresenterState.LinkGroup]) -> some View {
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

                        ForEach(Array(group.items.enumerated()), id: \.element.id) { index, item in
                            Button { onLinkTap(item) } label: {
                                Text(item.word)
                                    .font(appSkin.typography.monoEmphasis)
                                    .foregroundStyle(appSkin.palette.primaryText)
                            }
                            .buttonStyle(.plain)

                            if index < group.items.count - 1 {
                                Text("|")
                                    .font(appSkin.typography.caption)
                                    .foregroundStyle(appSkin.palette.quaternaryText)
                            }
                        }

                        if group.overflowCount > 0 {
                            Text("+\(group.overflowCount)")
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
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

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
    }

    // MARK: - Dynamic Example Budget
    //
    // 演算法：「中心展開填充」
    // 1. 從容器可用高度扣除 front card + padding → 得到答案卡上限
    // 2. 遍歷 backDocument 實際 blocks 計算佔用高度（含 VStack spacing）
    // 3. 剩餘空間 → 例句可用高度
    // 4. 可用高度 ÷ 行高 × 每行詞數 → 總詞預算 → truncateRadius
    //    radius 越大，以單字為中心向前後展開越多上下文
    //    空間不足時自動收縮，空間充裕時自然展開更多內容

    func answerExampleRadius(
        containerHeight: CGFloat,
        currentCard: TodayReviewPresenterState.CurrentCard
    ) -> Int {
        let measured = PerfLog.layout.measure(
            "todayReview.answerExampleRadius",
            "blocks=\(currentCard.backDocument.blocks.count)"
        ) {
        // ① 答案卡最大可用高度（geo.size.height 已扣除 topBar / bottomToolbar）
        let answerBudget = containerHeight
            - TodayReviewMetrics.cardTopInset
            - TodayReviewMetrics.cardBottomInset
            - frontCardHeight

        // ② combinedAnswerContent 固定元素
        let gap = TodayReviewMetrics.foldSectionSpacing
        var coreHeight = reviewCardPadding * 2                                  // fold padding top + bottom
            + TodayReviewMetrics.chevronButtonSize / 2                     // chevron pill 佔位
            + 20 + gap                                                          // tier label row
            + 36 + gap                                                          // word / translation
            + AppMetrics.dividerThin + gap                                      // CardSectionDivider (always shown)
            + 24 + gap                                                          // link strip / addLinkPrompt + gap

        // ③ Post-example blocks — pre-computed in CurrentCard, O(1) lookup
        coreHeight += currentCard.postExampleMetrics.totalHeight(gap: gap)

        // ④ 例句可用高度
        let exampleBudget = max(answerBudget - coreHeight, 0)

        // ⑤ 高度 → 行數 → 詞數 → radius
        let lineHeight: CGFloat = 22
        let textWidth = containerWidth
            - TodayReviewMetrics.cardHorizontalInset * 2
            - reviewCardPadding * 2
        let wordsPerLine = max(Int(textWidth / 62), 4)
        let lines = Int(exampleBudget / lineHeight)
        let totalWords = lines * wordsPerLine

        // 半徑 = 總預算的一半（前後各 radius 個詞），最小 3 保證可讀性
        return max(totalWords / 2, 3)
        }
        return measured.value
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
