//
//  CardSections.swift
//  BooksBrowser
//
//  共用卡片 Section 元件 — 渲染與業務邏輯完全分離
//  每個元件只接收「展示用資料」，無 @Query / @State / 副作用
//

import SwiftUI

// MARK: - CardSectionDivider

/// 卡片內部的水平分隔線（統一外觀，取代散落在各 View 的重複定義）
struct CardSectionDivider: View {
    @Environment(\.vocabSkin) private var vocabSkin
    var horizontalPadding: CGFloat = VocabSkin.baseMetrics.cardDividerHorizontalPadding

    var body: some View {
        Rectangle()
            .fill(vocabSkin.palette.divider)
            .frame(height: AppMetrics.dividerThin)
            .padding(.horizontal, horizontalPadding)
    }
}

// MARK: - CardSectionLabel

/// Section 標題標籤（icon + 小字）
struct CardSectionLabel: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    let systemImage: String

    var body: some View {
        Label {
            Text(title.localized)
                .font(vocabSkin.typography.caption)
        } icon: {
            Image(systemName: systemImage)
                .font(vocabSkin.typography.iconTiny)
        }
        .foregroundStyle(vocabSkin.palette.tertiaryText)
    }
}

// MARK: - CardHeroSection

/// 詳情頁頂部英雄區塊：單字 + 音標 + POS + Tier + 模式 + 翻譯
struct CardHeroSection: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.speechService) private var speechService
    @State private var copyTrigger = false
    let card: CardPresentation
    let colorScheme: ColorScheme

    var body: some View {
        VStack(alignment: .leading, spacing: vocabSkin.metrics.cardBlockContentGap) {
            HStack(alignment: .top, spacing: vocabSkin.metrics.cardBlockContentGap) {
                VStack(alignment: .leading, spacing: vocabSkin.metrics.cardBlockInnerGap) {
                    HStack(alignment: .firstTextBaseline, spacing: vocabSkin.spacing.heroBaselineGap) {
                        Text(card.word)
                            .font(vocabSkin.typography.detailWord)
                            .foregroundStyle(vocabSkin.palette.primaryText)
                            .minimumScaleFactor(0.85)

                        if let pos = card.partOfSpeech {
                            Text(pos)
                                .font(vocabSkin.typography.body.weight(.medium))
                                .foregroundStyle(vocabSkin.palette.secondaryText)
                        }

                        Button {
                            speechService.speak(card.word)
                            copyTrigger.toggle()
                        } label: {
                            Image(systemName: "speaker.wave.2.fill")
                                .font(vocabSkin.typography.iconSmall)
                                .foregroundStyle(vocabSkin.palette.secondaryText)
                                .symbolEffect(.bounce, value: copyTrigger)
                                .frame(width: vocabSkin.metrics.chromeButtonSize, height: vocabSkin.metrics.chromeButtonSize)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }

                }

                Spacer(minLength: vocabSkin.spacing.blockGap)

                if let tier = card.difficultyTier {
                    VocabTierLabel(tier: tier)
                }
            }

            HStack(spacing: vocabSkin.metrics.cardBlockInnerGap) {
                Text(card.reviewMode.localizedTitle)
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
            }

            Text(card.translation)
                .font(vocabSkin.typography.translationTitle)
                .foregroundStyle(vocabSkin.palette.translationText)
                .fixedSize(horizontal: false, vertical: true)
                .lineSpacing(vocabSkin.metrics.paragraphLineSpacing)
        }
        .contextMenu {
            Button("複製".localized, systemImage: "doc.on.doc") {
                UIPasteboard.general.string = card.word
                copyTrigger.toggle()
            }
        }
        .sensoryFeedback(.success, trigger: copyTrigger)
    }
}

// MARK: - CardExamplesSection

/// 例句渲染區塊
struct CardExamplesSection: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @State private var copyTrigger = false
    let examples: [String]
    let colorScheme: ColorScheme

    var body: some View {
        VStack(alignment: .leading, spacing: vocabSkin.metrics.cardBlockContentGap) {
            CardSectionLabel(title: "例句".localized, systemImage: "text.quote")

            ForEach(Array(examples.enumerated()), id: \.offset) { _, example in
                CardRichTextRenderer.text(
                    example,
                    style: CardRichTextStyle(
                        font: vocabSkin.typography.detailExampleSerif,
                        textColor: vocabSkin.palette.primaryText,
                        highlightColor: vocabSkin.palette.highlightMark,
                        italic: true,
                        underlineHighlights: vocabSkin.highlight.showUnderline,
                        useBackgroundMark: vocabSkin.highlight.showBackground,
                        highlightWeight: vocabSkin.highlight.fontWeight,
                        backgroundOpacity: vocabSkin.highlight.backgroundOpacity,
                        underlineOpacity: vocabSkin.highlight.underlineOpacity
                    ),
                    truncateAroundMarkedWordRadius: vocabSkin.metrics.exampleTruncateRadius
                )
                .lineSpacing(vocabSkin.metrics.paragraphLineSpacing)
            }
        }
        .contextMenu {
            Button("複製".localized, systemImage: "doc.on.doc") {
                UIPasteboard.general.string = examples.joined(separator: "\n")
                copyTrigger.toggle()
            }
        }
        .sensoryFeedback(.success, trigger: copyTrigger)
    }
}

// MARK: - CardSourceSection

/// 來源上下文 + 書名 + 章節
struct CardSourceSection: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @State private var copyTrigger = false
    let sourceContext: String
    let bookTitle: String
    let chapterTitle: String?

    private var copyText: String {
        var parts = [bookTitle]
        if let chapter = chapterTitle {
            parts.append(chapter)
        }
        return parts.joined(separator: " · ")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: vocabSkin.metrics.cardBlockInnerGap) {
            CardSectionLabel(title: "來源".localized, systemImage: "quote.opening")

            CardRichTextRenderer.text(
                sourceContext,
                style: CardRichTextStyle(
                    font: vocabSkin.typography.body,
                    textColor: vocabSkin.palette.secondaryText,
                    highlightColor: vocabSkin.palette.highlightMark,
                    italic: true
                )
            )
            .lineSpacing(vocabSkin.metrics.paragraphLineSpacing)

            HStack(spacing: vocabSkin.spacing.sourceMetadataGap) {
                Image(systemName: "book.closed")
                    .font(vocabSkin.typography.iconTiny)
                Text(bookTitle)
                if let chapter = chapterTitle {
                    Text("· \(chapter)")
                }
            }
            .font(vocabSkin.typography.caption)
            .foregroundStyle(vocabSkin.palette.quaternaryText)
        }
        .contextMenu {
            Button("複製".localized, systemImage: "doc.on.doc") {
                UIPasteboard.general.string = copyText
                copyTrigger.toggle()
            }
        }
        .sensoryFeedback(.success, trigger: copyTrigger)
    }
}

// MARK: - CardExplanationSection

/// 教學筆記（Rich Text）
struct CardExplanationSection: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @State private var copyTrigger = false
    let explanation: String
    let colorScheme: ColorScheme

    var body: some View {
        VStack(alignment: .leading, spacing: vocabSkin.metrics.cardBlockInnerGap) {
            CardSectionLabel(title: "教學筆記".localized, systemImage: "text.book.closed")

            CardRichTextRenderer.text(
                explanation,
                style: CardRichTextStyle(
                    font: vocabSkin.typography.body,
                    textColor: vocabSkin.palette.primaryText,
                    highlightColor: vocabSkin.palette.accent,
                    italic: false,
                    underlineHighlights: vocabSkin.highlight.showUnderline,
                    useBackgroundMark: vocabSkin.highlight.showBackground,
                    highlightWeight: vocabSkin.highlight.fontWeight,
                    backgroundOpacity: vocabSkin.highlight.backgroundOpacity,
                    underlineOpacity: vocabSkin.highlight.underlineOpacity
                )
            )
            .lineSpacing(vocabSkin.metrics.paragraphLineSpacing)
        }
        .contextMenu {
            Button("複製".localized, systemImage: "doc.on.doc") {
                UIPasteboard.general.string = explanation
                copyTrigger.toggle()
            }
        }
        .sensoryFeedback(.success, trigger: copyTrigger)
    }
}

// MARK: - CardFormsSection

/// 單字變化形列表
struct CardFormsSection: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @State private var copyTrigger = false
    let forms: [String]
    let rootForm: String?
    let colorScheme: ColorScheme

    var body: some View {
        VStack(alignment: .leading, spacing: vocabSkin.metrics.cardBlockInnerGap) {
            CardSectionLabel(title: "變化形".localized, systemImage: "text.badge.plus")

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: vocabSkin.metrics.cardBlockInnerGap) {
                    ForEach(Array(forms.enumerated()), id: \.offset) { _, form in
                        let isRoot = form == rootForm
                        Text(form)
                            .font(isRoot ? vocabSkin.typography.monoBodyStrong : vocabSkin.typography.monoBody)
                            .foregroundStyle(isRoot ? vocabSkin.palette.accent : vocabSkin.palette.secondaryText)
                    }
                }
            }
        }
        .contextMenu {
            Button("複製".localized, systemImage: "doc.on.doc") {
                UIPasteboard.general.string = forms.joined(separator: ", ")
                copyTrigger.toggle()
            }
        }
        .sensoryFeedback(.success, trigger: copyTrigger)
    }
}
