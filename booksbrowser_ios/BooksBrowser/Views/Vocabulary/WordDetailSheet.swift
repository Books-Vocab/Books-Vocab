//
//  WordDetailSheet.swift
//  BooksBrowser
//
//  單字詳情 Sheet — VocabularyListView 與 KGVocabView 共用
//

import SwiftUI
import Foundation
import SwiftData

struct WordDetailSheet: View {
    @Environment(\.colorScheme) private var colorScheme
    @Query private var allEntries: [VocabularyEntry]
    @State private var localLinkedCardStack: [VocabularyEntry] = []
    let entry: VocabularyEntry
    private let wrapInNavigation: Bool
    private let externalLinkedCardStack: Binding<[VocabularyEntry]>?

    private var paperBackground: Color {
        colorScheme == .dark ? AppColors.paperDark : AppColors.paperLight
    }

    init(
        entry: VocabularyEntry,
        wrapInNavigation: Bool = true,
        linkedCardStack: Binding<[VocabularyEntry]>? = nil
    ) {
        self.entry = entry
        self.wrapInNavigation = wrapInNavigation
        self.externalLinkedCardStack = linkedCardStack
    }

    var body: some View {
        Group {
            if wrapInNavigation {
                NavigationStack {
                    detailContent
                }
            } else {
                detailContent
            }
        }
    }

    private var card: CardPresentation {
        entry.cardPresentation
    }

    private var linkedCardStack: Binding<[VocabularyEntry]> {
        externalLinkedCardStack ?? $localLinkedCardStack
    }

    private var detailContent: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: AppMetrics.spacingLarge) {
                heroSection

                if !card.examples.isEmpty {
                    WordDetailSectionCard(
                        title: "例句",
                        systemImage: "text.quote",
                        tint: AppColors.translation(colorScheme)
                    ) {
                        VStack(alignment: .leading, spacing: AppMetrics.spacingMedium) {
                            ForEach(Array(card.examples.enumerated()), id: \.offset) { _, example in
                                CardRichTextRenderer.text(
                                    example,
                                    style: CardRichTextStyle(
                                        font: AppFonts.body(),
                                        textColor: .primary,
                                        highlightColor: AppColors.translation(colorScheme),
                                        italic: true
                                    ),
                                    truncateAroundMarkedWordRadius: 5
                                )
                            }
                        }
                    }
                }

                if card.showsSourceContext {
                    WordDetailSectionCard(
                        title: "來源",
                        systemImage: "quote.opening",
                        tint: .secondary
                    ) {
                        VStack(alignment: .leading, spacing: AppMetrics.spacingSmall) {
                            CardRichTextRenderer.text(
                                card.sourceContext,
                                style: CardRichTextStyle(
                                    font: AppFonts.body(),
                                    textColor: .secondary,
                                    highlightColor: .primary,
                                    italic: true
                                )
                            )

                            HStack(spacing: 6) {
                                Image(systemName: "book.closed")
                                Text(card.bookTitle)
                                if let chapter = card.chapterTitle {
                                    Text("· \(chapter)")
                                }
                            }
                            .font(AppFonts.caption())
                            .foregroundStyle(.tertiary)
                        }
                    }
                }

                if let explanation = card.explanation, !explanation.isEmpty {
                    WordDetailSectionCard(
                        title: "教學筆記",
                        systemImage: "text.book.closed",
                        tint: AppColors.accent(colorScheme)
                    ) {
                        CardRichTextRenderer.text(
                            explanation,
                            style: CardRichTextStyle(
                                font: AppFonts.body(),
                                textColor: .primary,
                                highlightColor: .primary,
                                italic: false
                            )
                        )
                    }
                }

                if !card.forms.isEmpty {
                    WordDetailSectionCard(
                        title: "變化形",
                        systemImage: "text.badge.plus",
                        tint: AppColors.translation(colorScheme)
                    ) {
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: AppMetrics.spacingSmall) {
                                ForEach(Array(card.forms.enumerated()), id: \.offset) { _, form in
                                    let isRoot = form == entry.rootForm
                                    AppTag(
                                        text: form,
                                        tone: isRoot ? AppColors.accent(colorScheme) : .secondary
                                    )
                                }
                            }
                        }
                    }
                }

                if !card.linkGroups.isEmpty {
                    WordDetailSectionCard(
                        title: "知識連結",
                        systemImage: "point.3.filled.connected.trianglepath",
                        tint: AppColors.translation(colorScheme)
                    ) {
                        VStack(alignment: .leading, spacing: AppMetrics.spacingMedium) {
                            ForEach(card.linkGroups) { group in
                                VStack(alignment: .leading, spacing: AppMetrics.spacingSmall) {
                                    Text(group.label)
                                        .font(AppFonts.caption(weight: .semibold))
                                        .foregroundStyle(.secondary)

                                    VStack(spacing: AppMetrics.spacingSmall) {
                                        ForEach(group.items) { link in
                                            graphLinkRow(link)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                WordDetailSectionCard(
                    title: "卡片資訊",
                    systemImage: "tray.full",
                    tint: .secondary
                ) {
                    VStack(spacing: AppMetrics.spacingSmall) {
                        WordDetailMetadataRow(title: "卡片模式") {
                            Text(card.reviewMode.localizedTitle)
                                .font(AppFonts.caption(weight: .medium))
                                .foregroundStyle(.secondary)
                        }
                        WordDetailMetadataRow(title: "加入日期") {
                            Text(card.dateAdded.formatted(date: .abbreviated, time: .omitted))
                                .font(AppFonts.caption(weight: .medium))
                                .foregroundStyle(.secondary)
                        }
                        WordDetailMetadataRow(title: "知識連結") {
                            Text("\(card.totalLinkCount)")
                                .font(AppFonts.caption(weight: .medium))
                                .foregroundStyle(.secondary)
                        }
                        WordDetailMetadataRow(title: "同步狀態") {
                            VocabularySyncBadge(
                                status: card.syncStatus,
                                successTone: AppColors.saved(colorScheme),
                                destructiveTone: AppColors.destructive(colorScheme)
                            )
                        }
                    }
                }
            }
            .padding(AppMetrics.spacingLarge)
        }
        .background(paperBackground.ignoresSafeArea())
        .navigationTitle(card.word)
        .navigationBarTitleDisplayMode(.inline)
        .overlay {
            LinkedCardOverlayStack(stack: linkedCardStack)
        }
    }

    // MARK: - Sections

    private var heroSection: some View {
        let tier = card.difficultyTier.map { AppColors.tier($0, scheme: colorScheme) }
        return WordDetailHeroCard(
            card: card,
            tierTone: tier?.color,
            tierLabel: tier?.label,
            accentTone: AppColors.accent(colorScheme),
            translationTone: AppColors.translation(colorScheme)
        )
    }

    @ViewBuilder
    private func graphLinkRow(_ link: KGCardLinkSummary) -> some View {
        WordDetailGraphLinkRow(
            link: link,
            onTap: entry.linkedEntry(for: link, in: allEntries).map { target in
                { linkedCardStack.wrappedValue.append(target) }
            }
        )
    }
}
