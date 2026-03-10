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
            .accessibilityLabel("複習卡片正面：\(card.word)")
            .accessibilityHint(state.revealStage.showsAnswer ? "" : "點一下翻轉卡片")
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

    // MARK: Answer Surface

    func answerFoldSurface(_ card: CardPresentation) -> some View {
        let answerText = card.reviewMode == .production ? card.word : card.translation
        return ReviewFoldSurface(position: state.revealStage.showsDetails ? .middle : .bottom) {
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
                    ReviewFoldChevronButton(action: onCollapseReveal)
                        .padding(reviewCardPadding)
                }
            }
        }
    }

    func answerFoldContent(_ card: CardPresentation, showsExpandHint: Bool) -> some View {
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
        .padding(.trailing, showsExpandHint ? TodayReviewMetrics.expandHintTrailingPadding : 0)
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

    // MARK: Detail Sheet

    func detailFoldSheet(_ currentCard: TodayReviewPresenterState.CurrentCard) -> some View {
        let card = currentCard.card
        return ReviewFoldSurface(position: .bottom) {
            VStack(alignment: .leading, spacing: vocabSkin.metrics.reviewFoldSectionSpacing) {
                HStack {
                    Spacer()
                    ReviewFoldChevronButton(action: onCollapseReveal)
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
        for block in card.document.blocks {
            switch block {
            case .hero, .meaning:
                pendingDivider = false
            case .divider:
                pendingDivider = true
            case .example, .source:
                if pendingDivider && !blocks.isEmpty { blocks.append(.divider) }
                blocks.append(block)
                pendingDivider = false
            }
        }
        return CardDocument(blocks: blocks)
    }
}
