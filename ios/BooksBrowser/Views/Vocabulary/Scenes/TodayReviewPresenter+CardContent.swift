import SwiftUI

// MARK: - Card Content Rendering

extension TodayReviewPresenter {

    // MARK: Dimensions

    var reviewCardPadding: CGFloat { appSkin.metrics.reviewFoldPadding }
    var frontCardHeight: CGFloat { appSkin.metrics.reviewFrontMinHeight }
    var answerCardHeight: CGFloat { appSkin.metrics.reviewAnswerMinHeight }

    // MARK: Front Surface

    func frontFoldSurface(_ card: CardPresentation) -> some View {
        ReviewFoldSurface(position: state.revealStage.showsAnswer ? .top : .single) {
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

    func reviewCardFront(_ card: CardPresentation) -> some View {
        VStack(alignment: .leading, spacing: appSkin.metrics.reviewFoldSectionSpacing) {
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
        .padding(.top, appSkin.metrics.reviewFoldHintBottomInset)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .frame(minHeight: frontCardHeight, alignment: .topLeading)
    }

    // MARK: Combined Answer Surface

    func answerFoldSurface(_ currentCard: TodayReviewPresenterState.CurrentCard, availableHeight: CGFloat) -> some View {
        let card = currentCard.card
        let answerText = card.reviewMode == .production ? card.word : card.translation
        return ReviewFoldSurface(position: .bottom) {
            combinedAnswerContent(currentCard, availableHeight: availableHeight)
                .accessibilityLabel(L10n.format("翻譯：%@", answerText))
        }
        .overlay(alignment: .top) {
            ReviewFoldChevronPill(action: onCollapseReveal)
                .offset(y: -appSkin.metrics.reviewChevronButtonSize / 2)
        }
    }

    func combinedAnswerContent(_ currentCard: TodayReviewPresenterState.CurrentCard, availableHeight: CGFloat) -> some View {
        let card = currentCard.card
        let hasLinks = !currentCard.linkGroups.isEmpty
        let exampleRadius = answerExampleRadius(
            containerHeight: availableHeight,
            currentCard: currentCard
        )
        return VStack(alignment: .leading, spacing: appSkin.metrics.reviewFoldSectionSpacing) {
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
        // ① 答案卡最大可用高度（geo.size.height 已扣除 topBar / bottomToolbar）
        let answerBudget = containerHeight
            - appSkin.metrics.reviewCardTopInset
            - appSkin.metrics.reviewCardBottomInset
            - frontCardHeight

        // ② combinedAnswerContent 固定元素
        let gap = appSkin.metrics.reviewFoldSectionSpacing
        var coreHeight = reviewCardPadding * 2                                  // fold padding top + bottom
            + appSkin.metrics.reviewChevronButtonSize / 2                     // chevron pill 佔位
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
            - appSkin.metrics.reviewCardHorizontalInset * 2
            - reviewCardPadding * 2
        let wordsPerLine = max(Int(textWidth / 62), 4)
        let lines = Int(exampleBudget / lineHeight)
        let totalWords = lines * wordsPerLine

        // 半徑 = 總預算的一半（前後各 radius 個詞），最小 3 保證可讀性
        return max(totalWords / 2, 3)
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
