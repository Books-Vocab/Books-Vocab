//
//  CardSections.swift
//  BooksBrowser
//
//  共用卡片 Section 元件 — 渲染與業務邏輯完全分離
//  每個元件只接收「展示用資料」，無 @Query / @State / 副作用
//

import SwiftUI
import Inject

// MARK: - CardSectionDivider

/// 卡片內部的水平分隔線（統一外觀，取代散落在各 View 的重複定義）
struct CardSectionDivider: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    var horizontalPadding: CGFloat = AppSkin.baseMetrics.cardDividerHorizontalPadding

    var body: some View {
        Rectangle()
            .fill(appSkin.palette.divider)
            .frame(height: AppMetrics.dividerThin)
            .padding(.horizontal, horizontalPadding)
            .enableInjection()
    }
}

// MARK: - CardSectionLabel

/// Section 標題標籤（icon + 小字）
struct CardSectionLabel: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    let title: String
    let systemImage: String

    var body: some View {
        Label {
            Text(title.localized)
                .font(appSkin.typography.caption)
        } icon: {
            Image(systemName: systemImage)
                .font(appSkin.typography.iconTiny)
        }
        .foregroundStyle(appSkin.palette.tertiaryText)
        .enableInjection()
    }
}

// MARK: - CardHeroSection

/// 詳情頁頂部英雄區塊：單字 + 音標 + POS + Tier + 模式 + 翻譯
struct CardHeroSection: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    @Environment(\.speechService) private var speechService
    @Environment(\.toastCoordinator) private var toastCoordinator
    @State private var copyTrigger = false
    let card: CardPresentation
    let colorScheme: ColorScheme

    var body: some View {
        VStack(alignment: .leading, spacing: appSkin.metrics.cardBlockContentGap) {
            HStack(alignment: .top, spacing: appSkin.metrics.cardBlockContentGap) {
                VStack(alignment: .leading, spacing: appSkin.metrics.cardBlockInnerGap) {
                    HStack(alignment: .firstTextBaseline, spacing: appSkin.spacing.heroBaselineGap) {
                        Text(card.word)
                            .font(appSkin.typography.detailWord)
                            .foregroundStyle(appSkin.palette.primaryText)
                            .minimumScaleFactor(0.85)

                        if let pos = card.partOfSpeech {
                            Text(pos)
                                .font(appSkin.typography.body.weight(.medium))
                                .foregroundStyle(appSkin.palette.secondaryText)
                        }

                        Button {
                            speechService.speak(card.word)
                            copyTrigger.toggle()
                        } label: {
                            Image(systemName: "speaker.wave.2.fill")
                                .font(appSkin.typography.iconSmall)
                                .foregroundStyle(appSkin.palette.secondaryText)
                                .symbolEffect(.bounce, value: copyTrigger)
                                .frame(width: appSkin.metrics.chromeButtonSize, height: appSkin.metrics.chromeButtonSize)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }

                }

                Spacer(minLength: appSkin.spacing.blockGap)

                if let tier = card.difficultyTier {
                    VocabTierLabel(tier: tier)
                }
            }

            HStack(spacing: appSkin.metrics.cardBlockInnerGap) {
                Text(card.reviewMode.localizedTitle)
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.tertiaryText)
            }

            Text(card.translation)
                .font(appSkin.typography.translationTitle)
                .foregroundStyle(appSkin.palette.translationText)
                .fixedSize(horizontal: false, vertical: true)
                .lineSpacing(appSkin.metrics.paragraphLineSpacing)
        }
        .contextMenu {
            Button("複製".localized, systemImage: "doc.on.doc") {
                PlatformClipboard.copy(card.word)
                copyTrigger.toggle()
                toastCoordinator.success("已複製")
            }
        }
        .sensoryFeedback(.success, trigger: copyTrigger)
        .enableInjection()
    }
}

// MARK: - CardExamplesSection

/// 例句渲染區塊
struct CardExamplesSection: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    @Environment(\.toastCoordinator) private var toastCoordinator
    @State private var copyTrigger = false
    let examples: [String]
    let colorScheme: ColorScheme

    var body: some View {
        VStack(alignment: .leading, spacing: appSkin.metrics.cardBlockContentGap) {
            CardSectionLabel(title: "例句".localized, systemImage: "text.quote")

            ForEach(Array(examples.enumerated()), id: \.offset) { _, example in
                CardRichTextRenderer.text(
                    example,
                    style: CardRichTextStyle(
                        font: appSkin.typography.detailExampleSerif,
                        textColor: appSkin.palette.primaryText,
                        highlightColor: appSkin.palette.highlightMark,
                        italic: true,
                        underlineHighlights: appSkin.highlight.showUnderline,
                        useBackgroundMark: appSkin.highlight.showBackground,
                        highlightWeight: appSkin.highlight.fontWeight,
                        backgroundOpacity: appSkin.highlight.backgroundOpacity,
                        underlineOpacity: appSkin.highlight.underlineOpacity
                    ),
                    truncateAroundMarkedWordRadius: appSkin.metrics.exampleTruncateRadius
                )
                .lineSpacing(appSkin.metrics.paragraphLineSpacing)
            }
        }
        .contextMenu {
            Button("複製".localized, systemImage: "doc.on.doc") {
                PlatformClipboard.copy(examples.joined(separator: "\n"))
                copyTrigger.toggle()
                toastCoordinator.success("已複製")
            }
        }
        .sensoryFeedback(.success, trigger: copyTrigger)
        .enableInjection()
    }
}

// MARK: - CardSourceSection

/// 來源上下文 + 書名 + 章節
struct CardSourceSection: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    @Environment(\.toastCoordinator) private var toastCoordinator
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
        VStack(alignment: .leading, spacing: appSkin.metrics.cardBlockInnerGap) {
            CardSectionLabel(title: "來源".localized, systemImage: "book.closed")

            HStack(spacing: appSkin.spacing.sourceMetadataGap) {
                Text(bookTitle)
                if let chapter = chapterTitle {
                    Text("· \(chapter)")
                }
            }
            .font(appSkin.typography.caption)
            .foregroundStyle(appSkin.palette.secondaryText)
        }
        .contextMenu {
            Button("複製".localized, systemImage: "doc.on.doc") {
                PlatformClipboard.copy(copyText)
                copyTrigger.toggle()
                toastCoordinator.success("已複製")
            }
        }
        .sensoryFeedback(.success, trigger: copyTrigger)
        .enableInjection()
    }
}

// MARK: - CardExplanationSection

/// 教學筆記（Rich Text）
struct CardExplanationSection: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    @Environment(\.toastCoordinator) private var toastCoordinator
    @State private var copyTrigger = false
    let explanation: String
    let colorScheme: ColorScheme

    var body: some View {
        VStack(alignment: .leading, spacing: appSkin.metrics.cardBlockInnerGap) {
            CardSectionLabel(title: "教學筆記".localized, systemImage: "text.book.closed")

            CardRichTextRenderer.text(
                explanation,
                style: CardRichTextStyle(
                    font: appSkin.typography.body,
                    textColor: appSkin.palette.primaryText,
                    highlightColor: appSkin.palette.accent,
                    italic: false,
                    underlineHighlights: appSkin.highlight.showUnderline,
                    useBackgroundMark: appSkin.highlight.showBackground,
                    highlightWeight: appSkin.highlight.fontWeight,
                    backgroundOpacity: appSkin.highlight.backgroundOpacity,
                    underlineOpacity: appSkin.highlight.underlineOpacity
                )
            )
            .lineSpacing(appSkin.metrics.paragraphLineSpacing)
        }
        .contextMenu {
            Button("複製".localized, systemImage: "doc.on.doc") {
                PlatformClipboard.copy(explanation)
                copyTrigger.toggle()
                toastCoordinator.success("已複製")
            }
        }
        .sensoryFeedback(.success, trigger: copyTrigger)
        .enableInjection()
    }
}

// MARK: - CardFormsSection

/// 單字變化形列表
struct CardFormsSection: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    @Environment(\.toastCoordinator) private var toastCoordinator
    @State private var copyTrigger = false
    let forms: [String]
    let rootForm: String?
    let colorScheme: ColorScheme

    var body: some View {
        VStack(alignment: .leading, spacing: appSkin.metrics.cardBlockInnerGap) {
            CardSectionLabel(title: "變化形".localized, systemImage: "text.badge.plus")

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: appSkin.metrics.cardBlockInnerGap) {
                    ForEach(Array(forms.enumerated()), id: \.offset) { _, form in
                        let isRoot = form == rootForm
                        Text(form)
                            .font(isRoot ? appSkin.typography.monoBodyStrong : appSkin.typography.monoBody)
                            .foregroundStyle(isRoot ? appSkin.palette.accent : appSkin.palette.secondaryText)
                    }
                }
            }
        }
        .contextMenu {
            Button("複製".localized, systemImage: "doc.on.doc") {
                PlatformClipboard.copy(forms.joined(separator: ", "))
                copyTrigger.toggle()
                toastCoordinator.success("已複製")
            }
        }
        .sensoryFeedback(.success, trigger: copyTrigger)
        .enableInjection()
    }
}
