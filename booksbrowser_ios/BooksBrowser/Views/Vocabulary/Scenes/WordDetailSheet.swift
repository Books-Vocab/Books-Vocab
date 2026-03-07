//
//  WordDetailSheet.swift
//  BooksBrowser
//
//  單字詳情 — Mochi 式單卡整合佈局（ONE card + Divider 分隔 sections）
//

import SwiftUI
import Foundation
import SwiftData

struct WordDetailSheet: View {
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.vocabSkin) private var vocabSkin
    @Query private var allEntries: [VocabularyEntry]
    @State private var localLinkedCardStack: [VocabularyEntry] = []
    let entry: VocabularyEntry
    private let wrapInNavigation: Bool
    private let externalLinkedCardStack: Binding<[VocabularyEntry]>?

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
                VStack(spacing: 0) {
                    VocabOverlayHeader(
                        title: card.word,
                        systemImage: "book.closed",
                        onClose: {
                            // When wrapInNavigation is true, this is the root sheet.
                            // We need a way to dismiss the root sheet. Since we don't have
                            // @Environment(\.dismiss) yet, I will add it.
                            dismiss()
                        }
                    )
                    
                    detailContentScroll
                }
                .vocabCanvasBackground()
            } else {
                detailContentScroll
            }
        }
    }

    @Environment(\.dismiss) private var dismiss
    
    private var card: CardPresentation {
        entry.cardPresentation
    }

    private var linkedCardStack: Binding<[VocabularyEntry]> {
        externalLinkedCardStack ?? $localLinkedCardStack
    }

    // MARK: - Single Card Layout

    private var detailContentScroll: some View {
        ScrollView {
            VocabCard(padding: 0) {
                VStack(alignment: .leading, spacing: 0) {
                    // ─── Hero ───
                    CardHeroSection(card: card, colorScheme: colorScheme)
                        .padding(AppMetrics.spacingLarge)

                    // ─── Examples ───
                    if !card.examples.isEmpty {
                        CardSectionDivider()
                        CardExamplesSection(examples: card.examples, colorScheme: colorScheme)
                            .padding(AppMetrics.spacingLarge)
                    }

                    // ─── Source ───
                    if card.showsSourceContext {
                        CardSectionDivider()
                        CardSourceSection(
                            sourceContext: card.sourceContext,
                            bookTitle: card.bookTitle,
                            chapterTitle: card.chapterTitle
                        )
                        .padding(AppMetrics.spacingLarge)
                    }

                    // ─── Explanation ───
                    if let explanation = card.explanation, !explanation.isEmpty {
                        CardSectionDivider()
                        CardExplanationSection(explanation: explanation, colorScheme: colorScheme)
                            .padding(AppMetrics.spacingLarge)
                    }

                    // ─── Forms ───
                    if !card.forms.isEmpty {
                        CardSectionDivider()
                        CardFormsSection(
                            forms: card.forms,
                            rootForm: entry.rootForm,
                            colorScheme: colorScheme
                        )
                        .padding(AppMetrics.spacingLarge)
                    }

                    // ─── Links ───
                    if !card.linkGroups.isEmpty {
                        CardSectionDivider()
                        linksSection
                            .padding(AppMetrics.spacingLarge)
                    }

                    // ─── Metadata footer ───
                    CardSectionDivider()
                    metadataFooter
                        .padding(AppMetrics.spacingLarge)
                }
            }
            .padding(AppMetrics.spacingLarge)
            .padding(.bottom, AppMetrics.spacingLarge * 2) // Extra padding for scrolling
        }
        .scrollContentBackground(.hidden)
        .vocabCanvasBackground()
        .overlay {
            // Only top-level WordDetailSheet renders the overlay stack.
            // Inner sheets (inside LinkedCardOverlayStack) share the same binding
            // but must NOT create a nested overlay — that causes infinite recursion.
            if wrapInNavigation {
                LinkedCardOverlayStack(stack: linkedCardStack)
            }
        }
    }



    // MARK: - Links

    private var linksSection: some View {
        VStack(alignment: .leading, spacing: AppMetrics.spacingMedium) {
            CardSectionLabel(title: "知識連結", systemImage: "link")

            ForEach(card.linkGroups) { group in
                VStack(alignment: .leading, spacing: AppMetrics.spacingSmall) {
                    Text(group.label)
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.tertiaryText)

                    ForEach(group.items) { link in
                        graphLinkRow(link)
                    }
                }
            }
        }
    }

    // MARK: - Metadata Footer

    private var metadataFooter: some View {
        HStack(spacing: AppMetrics.spacingLarge) {
            metaItem(
                icon: "calendar",
                text: card.dateAdded.formatted(date: .abbreviated, time: .omitted)
            )
            metaItem(
                icon: "link",
                text: "\(card.totalLinkCount) connections"
            )
            metaItem(
                icon: card.syncStatus == 1 ? "checkmark.circle" : "clock",
                text: card.syncStatus == 1 ? "已同步" : "待同步"
            )
        }
        .font(vocabSkin.typography.caption)
        .foregroundStyle(vocabSkin.palette.quaternaryText)
    }

    private func metaItem(icon: String, text: String) -> some View {
        HStack(spacing: 4) {
            Image(systemName: icon)
                .font(.system(size: 10, weight: .thin))
            Text(text)
        }
    }

    // MARK: - Helpers

    @ViewBuilder
    private func graphLinkRow(_ link: KGCardLinkSummary) -> some View {
        let target = entry.linkedEntry(for: link, in: allEntries)
        WordDetailGraphLinkRow(
            link: link,
            onTap: target.map { t in
                {
                    linkedCardStack.wrappedValue.append(t)
                }
            }
        )
    }
}
