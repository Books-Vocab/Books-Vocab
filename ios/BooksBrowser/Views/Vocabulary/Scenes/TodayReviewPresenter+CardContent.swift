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
                    .frame(height: frontCardHeight, alignment: .topLeading)
            }
            .buttonStyle(.plain)
            .frame(maxWidth: .infinity, alignment: .topLeading)
            .frame(height: frontCardHeight, alignment: .topLeading)
            .contentShape(Rectangle())
            .disabled(state.revealStage.showsAnswer || !isCardInteractive)
            .accessibilityLabel(L10n.format("複習卡片正面：%@", card.word))
            .accessibilityHint(state.revealStage.showsAnswer ? "" : "點一下翻轉卡片".localized)
        }
    }

    func reviewCardFront(_ card: CardPresentation) -> some View {
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
                    truncateAroundMarkedWordRadius: vocabSkin.metrics.exampleTruncateRadius,
                    targetWord: card.word
                )
                .lineSpacing(vocabSkin.metrics.paragraphLineSpacing)
            }

            Spacer(minLength: vocabSkin.metrics.reviewTopBarTopInset)
        }
        .padding(reviewCardPadding)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .frame(height: frontCardHeight, alignment: .topLeading)
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
        let exampleRadius = answerExampleRadius(
            containerHeight: availableHeight,
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
                            .lineLimit(3)
                    }
                }
            }

            let backDoc = reviewBackDocument(for: card)
            if !backDoc.blocks.isEmpty {
                CardSectionDivider(horizontalPadding: 0)
                CardDocumentView(document: backDoc, truncateRadius: exampleRadius, targetWord: card.word)
            }

            if hasLinks {
                CardSectionDivider(horizontalPadding: 0)
                reviewLinkStrip(currentCard.linkGroups)
            }
        }
        .padding(reviewCardPadding)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .frame(minHeight: answerCardHeight, alignment: .topLeading)
    }

    func answerMeaningParagraphs(for card: CardPresentation) -> [CardDocumentParagraph] {
        for block in card.document.blocks {
            if case .meaning(let meaning) = block {
                return meaning.paragraphs
            }
        }
        return []
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
    // 2. 估算核心內容（word、pronunciation、meaning、links、padding）的佔用高度
    // 3. 剩餘空間扣除來源區塊預留 → 例句可用高度
    // 4. 可用高度 ÷ 行高 × 每行詞數 → 總詞預算 → truncateRadius
    //    radius 越大，以單字為中心向前後展開越多上下文
    //    空間不足時自動收縮，空間充裕時自然展開更多內容

    func answerExampleRadius(
        containerHeight: CGFloat,
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

        if let p = card.pronunciation, !p.isEmpty {
            coreHeight += 20 + gap                                              // pronunciation
        }

        let meaningCount = answerMeaningParagraphs(for: card).count
        if meaningCount > 0 {
            // divider(17) + 每段最多 3 行（lineLimit）× 行高 22
            coreHeight += 17 + CGFloat(min(meaningCount, 3)) * 22 + gap
        }

        if hasLinks {
            coreHeight += 17 + 24 + gap                                         // divider + link strip
        }

        // ③ 來源區塊固定預留 + divider
        let sourceReserve: CGFloat = 80
        let exampleBudget = max(answerBudget - coreHeight - sourceReserve - 17, 0)

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

    func reviewBackDocument(for card: CardPresentation) -> CardDocument {
        var blocks: [CardDocumentBlock] = []
        var pendingDivider = false
        var exampleCount = 0
        var sourceCount = 0
        for block in card.document.blocks {
            switch block {
            case .hero, .meaning:
                pendingDivider = false
            case .divider:
                pendingDivider = true
            case .example:
                guard exampleCount < 1 else { continue }
                if pendingDivider && !blocks.isEmpty { blocks.append(.divider) }
                blocks.append(block)
                pendingDivider = false
                exampleCount += 1
            case .source:
                guard sourceCount < 1 else { continue }
                if pendingDivider && !blocks.isEmpty { blocks.append(.divider) }
                blocks.append(block)
                pendingDivider = false
                sourceCount += 1
            }
        }
        return CardDocument(blocks: blocks)
    }
}
