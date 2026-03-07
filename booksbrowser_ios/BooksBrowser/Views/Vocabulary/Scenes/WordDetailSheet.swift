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

    // MARK: - Single Card Layout

    private var detailContent: some View {
        ScrollView {
            AppCard(padding: 0) {
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
        }
        .scrollContentBackground(.hidden)
        .background(AppColors.paperLight.ignoresSafeArea())
        .navigationTitle(card.word)
        .navigationBarTitleDisplayMode(.inline)
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
                        .font(AppFonts.caption(weight: .medium))
                        .foregroundStyle(.tertiary)

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
        .font(AppFonts.caption())
        .foregroundStyle(.quaternary)
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
        let _ = print("[DEBUG-LINK] link.word=\(link.word) link.cardId=\(link.cardId) target=\(target?.word ?? "NIL") allEntries.count=\(allEntries.count)")
        WordDetailGraphLinkRow(
            link: link,
            onTap: target.map { t in
                {
                    print("[DEBUG-LINK] TAP FIRED for \(link.word) -> appending \(t.word) to stack")
                    linkedCardStack.wrappedValue.append(t)
                    print("[DEBUG-LINK] stack count now: \(linkedCardStack.wrappedValue.count)")
                }
            }
        )
    }
}
