import SwiftUI

// MARK: - Card Content Rendering

extension TodayReviewPresenter {

    // MARK: Dimensions

    var reviewCardPadding: CGFloat { vocabSkin.metrics.reviewFoldPadding }
    var frontCardHeight: CGFloat { vocabSkin.metrics.reviewFrontMinHeight }
    var answerCardHeight: CGFloat { vocabSkin.metrics.reviewAnswerMinHeight }

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
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
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

                if let pos = card.partOfSpeech {
                    Text(pos)
                        .font(vocabSkin.typography.body)
                        .foregroundStyle(vocabSkin.palette.tertiaryText)
                }
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
                    truncateAroundMarkedWordRadius: vocabSkin.metrics.exampleTruncateRadius,
                    targetWord: card.word
                )
                .lineSpacing(vocabSkin.metrics.paragraphLineSpacing)
            }
        }
        .padding(reviewCardPadding)
        .padding(.top, vocabSkin.metrics.reviewFoldHintBottomInset)
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
                .offset(y: -vocabSkin.metrics.reviewChevronButtonSize / 2)
        }
    }

    func combinedAnswerContent(_ currentCard: TodayReviewPresenterState.CurrentCard, availableHeight: CGFloat) -> some View {
        let card = currentCard.card
        let hasLinks = !currentCard.linkGroups.isEmpty
        let hasMeaning = currentCard.backDocument.blocks.contains { if case .meaning = $0 { return true }; return false }
        let exampleRadius = answerExampleRadius(
            containerHeight: availableHeight,
            hasMeaning: hasMeaning,
            card: card,
            hasLinks: hasLinks
        )
        return VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
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
            .foregroundStyle(vocabSkin.palette.primaryText)
            .lineLimit(3)
            .minimumScaleFactor(0.65)
            .fixedSize(horizontal: false, vertical: true)

            if hasLinks {
                CardSectionDivider(horizontalPadding: 0)
                reviewLinkStrip(currentCard.linkGroups)
            }

            if !currentCard.backDocument.blocks.isEmpty {
                CardDocumentView(document: currentCard.backDocument, truncateRadius: exampleRadius, targetWord: card.word, compact: true)
            }
        }
        .padding(reviewCardPadding)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .frame(minHeight: answerCardHeight, alignment: .topLeading)
    }

    // MARK: Link Strip

    func reviewLinkStrip(_ groups: [TodayReviewPresenterState.LinkGroup]) -> some View {
        HStack(alignment: .top, spacing: vocabSkin.spacing.inlineGap) {
            Image(systemName: "paperclip")
                .font(vocabSkin.typography.iconTiny)
                .foregroundStyle(vocabSkin.palette.tertiaryText)
                .padding(.top, TodayReviewMetrics.answerHintTopPadding)

            VStack(alignment: .leading, spacing: vocabSkin.spacing.inlineGap) {
                ForEach(groups) { group in
                    HStack(spacing: 4) {
                        Text(group.label.localized + "：")
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.tertiaryText)

                        ForEach(Array(group.items.enumerated()), id: \.element.id) { index, item in
                            Button { onLinkTap(item) } label: {
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

    // MARK: - Dynamic Example Budget
    //
    // 演算法：「中心展開填充」
    // 1. 從容器可用高度扣除 front card + padding → 得到答案卡上限
    // 2. 估算核心內容（word、meaning、links、padding）的佔用高度
    // 3. 剩餘空間扣除來源區塊預留 → 例句可用高度
    // 4. 可用高度 ÷ 行高 × 每行詞數 → 總詞預算 → truncateRadius
    //    radius 越大，以單字為中心向前後展開越多上下文
    //    空間不足時自動收縮，空間充裕時自然展開更多內容

    func answerExampleRadius(
        containerHeight: CGFloat,
        hasMeaning: Bool,
        card: CardPresentation,
        hasLinks: Bool
    ) -> Int {
        // ① 答案卡最大可用高度（geo.size.height 已扣除 topBar / bottomToolbar）
        let answerBudget = containerHeight
            - vocabSkin.metrics.reviewCardTopInset
            - vocabSkin.metrics.reviewCardBottomInset
            - frontCardHeight

        // ② 核心內容估算高度
        let gap = vocabSkin.spacing.sectionGap
        var coreHeight = reviewCardPadding * 2                                  // fold padding top + bottom
            + vocabSkin.metrics.reviewChevronButtonSize / 2                     // chevron pill 佔位
            + 20 + gap                                                          // tier label row
            + 36 + gap                                                          // word / translation

        if hasMeaning {
            // divider(17) + 最多 3 行 explanation(22×3) + collocations 估算(30)
            // reviewBackSubset 已去除 meaning title，不再計入 title 高度
            coreHeight += 17 + 66 + 30 + gap
        }

        if hasLinks {
            coreHeight += 17 + 24 + gap                                         // divider + link strip
        }

        // ③ 例句在最後，佔用全部剩餘空間（含 divider）
        let exampleBudget = max(answerBudget - coreHeight - 17, 0)

        // ④ 高度 → 行數 → 詞數 → radius
        let lineHeight: CGFloat = 22
        let textWidth = containerWidth
            - vocabSkin.metrics.reviewCardHorizontalInset * 2
            - reviewCardPadding * 2
        let wordsPerLine = max(Int(textWidth / 52), 4)
        let lines = Int(exampleBudget / lineHeight)
        let totalWords = lines * wordsPerLine

        // 半徑 = 總預算的一半（前後各 radius 個詞），最小 3 保證可讀性
        return max(totalWords / 2, 3)
    }

    // MARK: Fonts

    func reviewFrontWordFont(for text: String) -> Font {
        let count = text.count
        if count > 20 { return .system(size: TodayReviewMetrics.counterFontSizeCompact, weight: .semibold, design: .monospaced) }
        if count > 12 { return .system(size: TodayReviewMetrics.counterFontSizeMedium, weight: .semibold, design: .monospaced) }
        return .system(size: 30, weight: .semibold, design: .monospaced)
    }

    func reviewAnswerWordFont(for text: String) -> Font {
        let count = text.count
        if count > 20 { return vocabSkin.typography.translationTitle }
        if count > 12 { return .system(size: TodayReviewMetrics.counterFontSizeLarge, weight: .semibold, design: .monospaced) }
        return vocabSkin.typography.reviewWord
    }

}
