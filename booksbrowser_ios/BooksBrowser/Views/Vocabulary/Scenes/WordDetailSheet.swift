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
                    heroSection
                        .padding(AppMetrics.spacingLarge)

                    // ─── Examples ───
                    if !card.examples.isEmpty {
                        sectionDivider
                        examplesSection
                            .padding(AppMetrics.spacingLarge)
                    }

                    // ─── Source ───
                    if card.showsSourceContext {
                        sectionDivider
                        sourceSection
                            .padding(AppMetrics.spacingLarge)
                    }

                    // ─── Explanation ───
                    if let explanation = card.explanation, !explanation.isEmpty {
                        sectionDivider
                        explanationSection(explanation)
                            .padding(AppMetrics.spacingLarge)
                    }

                    // ─── Forms ───
                    if !card.forms.isEmpty {
                        sectionDivider
                        formsSection
                            .padding(AppMetrics.spacingLarge)
                    }

                    // ─── Links ───
                    if !card.linkGroups.isEmpty {
                        sectionDivider
                        linksSection
                            .padding(AppMetrics.spacingLarge)
                    }

                    // ─── Metadata footer ───
                    sectionDivider
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
            LinkedCardOverlayStack(stack: linkedCardStack)
        }
    }

    private var sectionDivider: some View {
        Rectangle()
            .fill(Color.primary.opacity(0.06))
            .frame(height: 0.5)
            .padding(.horizontal, AppMetrics.spacingLarge)
    }

    // MARK: - Hero

    private var heroSection: some View {
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

    // MARK: - Examples

    private var examplesSection: some View {
        VStack(alignment: .leading, spacing: AppMetrics.spacingMedium) {
            sectionLabel("例句", systemImage: "text.quote")

            ForEach(Array(card.examples.enumerated()), id: \.offset) { _, example in
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

    // MARK: - Source

    private var sourceSection: some View {
        VStack(alignment: .leading, spacing: AppMetrics.spacingSmall) {
            sectionLabel("來源", systemImage: "quote.opening")

            CardRichTextRenderer.text(
                card.sourceContext,
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
                Text(card.bookTitle)
                if let chapter = card.chapterTitle {
                    Text("· \(chapter)")
                }
            }
            .font(AppFonts.caption())
            .foregroundStyle(.quaternary)
        }
    }

    // MARK: - Explanation

    private func explanationSection(_ explanation: String) -> some View {
        VStack(alignment: .leading, spacing: AppMetrics.spacingSmall) {
            sectionLabel("教學筆記", systemImage: "text.book.closed")

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

    // MARK: - Forms

    private var formsSection: some View {
        VStack(alignment: .leading, spacing: AppMetrics.spacingSmall) {
            sectionLabel("變化形", systemImage: "text.badge.plus")

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: AppMetrics.spacingSmall) {
                    ForEach(Array(card.forms.enumerated()), id: \.offset) { _, form in
                        let isRoot = form == entry.rootForm
                        Text(form)
                            .font(.system(size: 14, weight: isRoot ? .semibold : .regular, design: .monospaced))
                            .foregroundStyle(isRoot ? AppColors.accent(colorScheme) : .secondary)
                    }
                }
            }
        }
    }

    // MARK: - Links

    private var linksSection: some View {
        VStack(alignment: .leading, spacing: AppMetrics.spacingMedium) {
            sectionLabel("知識連結", systemImage: "point.3.filled.connected.trianglepath")

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
                icon: "point.3.connected.trianglepath",
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

    private func sectionLabel(_ title: String, systemImage: String) -> some View {
        Label {
            Text(title)
                .font(AppFonts.caption(weight: .medium))
        } icon: {
            Image(systemName: systemImage)
                .font(.system(size: 10, weight: .thin))
        }
        .foregroundStyle(.tertiary)
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
