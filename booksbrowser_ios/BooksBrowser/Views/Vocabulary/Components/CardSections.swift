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
    var horizontalPadding: CGFloat = AppMetrics.spacingLarge

    var body: some View {
        Rectangle()
            .fill(Color.primary.opacity(0.06))
            .frame(height: 0.5)
            .padding(.horizontal, horizontalPadding)
    }
}

// MARK: - CardSectionLabel

/// Section 標題標籤（icon + 小字）
struct CardSectionLabel: View {
    let title: String
    let systemImage: String

    var body: some View {
        Label {
            Text(title)
                .font(AppFonts.caption(weight: .medium))
        } icon: {
            Image(systemName: systemImage)
                .font(.system(size: 10, weight: .thin))
        }
        .foregroundStyle(.tertiary)
    }
}

// MARK: - CardHeroSection

/// 詳情頁頂部英雄區塊：單字 + 音標 + POS + Tier + 模式 + 翻譯
struct CardHeroSection: View {
    let card: CardPresentation
    let colorScheme: ColorScheme

    var body: some View {
        VStack(alignment: .leading, spacing: AppMetrics.spacingMedium) {
            HStack(alignment: .top, spacing: AppMetrics.spacingMedium) {
                VStack(alignment: .leading, spacing: AppMetrics.spacingSmall) {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(card.word)
                            .font(AppFonts.hero(weight: .semibold))
                            .foregroundStyle(.primary)
                            .minimumScaleFactor(0.85)

                        if let pos = card.partOfSpeech {
                            Text(pos)
                                .font(AppFonts.subhead(weight: .medium))
                                .foregroundStyle(.tertiary)
                        }
                    }

                    if let pron = card.pronunciation, !pron.isEmpty {
                        Text("/\(pron)/")
                            .font(AppFonts.subhead())
                            .foregroundStyle(.quaternary)
                    }
                }

                Spacer(minLength: 12)

                if let tier = card.difficultyTier {
                    let (color, label) = AppColors.tier(tier, scheme: colorScheme)
                    Text(label)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(color)
                }
            }

            HStack(spacing: AppMetrics.spacingSmall) {
                Text(card.reviewMode.localizedTitle)
                    .font(AppFonts.caption(weight: .medium))
                    .foregroundStyle(.tertiary)
            }

            Text(card.translation)
                .font(AppFonts.h2(weight: .semibold))
                .foregroundStyle(AppColors.translation(colorScheme))
                .fixedSize(horizontal: false, vertical: true)
                .lineSpacing(4)
        }
    }
}

// MARK: - CardExamplesSection

/// 例句渲染區塊
struct CardExamplesSection: View {
    let examples: [String]
    let colorScheme: ColorScheme

    var body: some View {
        VStack(alignment: .leading, spacing: AppMetrics.spacingMedium) {
            CardSectionLabel(title: "例句", systemImage: "text.quote")

            ForEach(Array(examples.enumerated()), id: \.offset) { _, example in
                CardRichTextRenderer.text(
                    example,
                    style: CardRichTextStyle(
                        font: AppFonts.body(),
                        textColor: .primary,
                        highlightColor: AppColors.highlightMark,
                        italic: true
                    ),
                    truncateAroundMarkedWordRadius: 5
                )
                .lineSpacing(4)
            }
        }
    }
}

// MARK: - CardSourceSection

/// 來源上下文 + 書名 + 章節
struct CardSourceSection: View {
    let sourceContext: String
    let bookTitle: String
    let chapterTitle: String?

    var body: some View {
        VStack(alignment: .leading, spacing: AppMetrics.spacingSmall) {
            CardSectionLabel(title: "來源", systemImage: "quote.opening")

            CardRichTextRenderer.text(
                sourceContext,
                style: CardRichTextStyle(
                    font: AppFonts.body(),
                    textColor: .secondary,
                    highlightColor: AppColors.highlightMark,
                    italic: true
                )
            )
            .lineSpacing(4)

            HStack(spacing: 6) {
                Image(systemName: "book.closed")
                    .font(.system(size: 10, weight: .thin))
                Text(bookTitle)
                if let chapter = chapterTitle {
                    Text("· \(chapter)")
                }
            }
            .font(AppFonts.caption())
            .foregroundStyle(.quaternary)
        }
    }
}

// MARK: - CardExplanationSection

/// 教學筆記（Rich Text）
struct CardExplanationSection: View {
    let explanation: String
    let colorScheme: ColorScheme

    var body: some View {
        VStack(alignment: .leading, spacing: AppMetrics.spacingSmall) {
            CardSectionLabel(title: "教學筆記", systemImage: "text.book.closed")

            CardRichTextRenderer.text(
                explanation,
                style: CardRichTextStyle(
                    font: AppFonts.body(),
                    textColor: .primary,
                    highlightColor: AppColors.accent(colorScheme),
                    italic: false
                )
            )
            .lineSpacing(4)
        }
    }
}

// MARK: - CardFormsSection

/// 單字變化形列表
struct CardFormsSection: View {
    let forms: [String]
    let rootForm: String?
    let colorScheme: ColorScheme

    var body: some View {
        VStack(alignment: .leading, spacing: AppMetrics.spacingSmall) {
            CardSectionLabel(title: "變化形", systemImage: "text.badge.plus")

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: AppMetrics.spacingSmall) {
                    ForEach(Array(forms.enumerated()), id: \.offset) { _, form in
                        let isRoot = form == rootForm
                        Text(form)
                            .font(.system(size: 14, weight: isRoot ? .semibold : .regular, design: .monospaced))
                            .foregroundStyle(isRoot ? AppColors.accent(colorScheme) : .secondary)
                    }
                }
            }
        }
    }
}
