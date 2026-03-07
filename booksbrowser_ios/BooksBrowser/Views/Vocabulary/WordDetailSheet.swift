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
    @State private var selectedLinkedEntry: VocabularyEntry?
    let entry: VocabularyEntry
    private let wrapInNavigation: Bool

    private var paperBackground: Color {
        colorScheme == .dark ? AppColors.paperDark : AppColors.paperLight
    }

    init(entry: VocabularyEntry, wrapInNavigation: Bool = true) {
        self.entry = entry
        self.wrapInNavigation = wrapInNavigation
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

    private var detailContent: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: AppMetrics.spacingLarge) {
                heroSection

                if !displayedExamples.isEmpty {
                    contentSection(
                        title: "例句",
                        systemImage: "text.quote",
                        tint: AppColors.translation(colorScheme)
                    ) {
                        VStack(alignment: .leading, spacing: AppMetrics.spacingMedium) {
                            ForEach(Array(displayedExamples.enumerated()), id: \.offset) { _, example in
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

                if showsSourceContext {
                    contentSection(
                        title: "來源",
                        systemImage: "quote.opening",
                        tint: .secondary
                    ) {
                        VStack(alignment: .leading, spacing: AppMetrics.spacingSmall) {
                            CardRichTextRenderer.text(
                                entry.context,
                                style: CardRichTextStyle(
                                    font: AppFonts.body(),
                                    textColor: .secondary,
                                    highlightColor: .primary,
                                    italic: true
                                )
                            )

                            HStack(spacing: 6) {
                                Image(systemName: "book.closed")
                                Text(entry.bookTitle)
                                if let chapter = entry.chapterTitle {
                                    Text("· \(chapter)")
                                }
                            }
                            .font(AppFonts.caption())
                            .foregroundStyle(.tertiary)
                        }
                    }
                }

                if let explanation = entry.explanation, !explanation.isEmpty {
                    contentSection(
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

                if !allForms.isEmpty {
                    contentSection(
                        title: "變化形",
                        systemImage: "text.badge.plus",
                        tint: AppColors.translation(colorScheme)
                    ) {
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: AppMetrics.spacingSmall) {
                                ForEach(Array(allForms.enumerated()), id: \.offset) { _, form in
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

                if !linkGroups.isEmpty {
                    contentSection(
                        title: "知識連結",
                        systemImage: "point.3.filled.connected.trianglepath",
                        tint: AppColors.translation(colorScheme)
                    ) {
                        VStack(alignment: .leading, spacing: AppMetrics.spacingMedium) {
                            ForEach(linkGroups) { group in
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

                contentSection(
                    title: "卡片資訊",
                    systemImage: "tray.full",
                    tint: .secondary
                ) {
                    VStack(spacing: AppMetrics.spacingSmall) {
                        metadataRow("卡片模式", value: entry.reviewMode.localizedTitle)
                        metadataRow("加入日期", value: entry.dateAdded.formatted(date: .abbreviated, time: .omitted))
                        metadataRow("知識連結", value: "\(linkGroups.reduce(0) { $0 + $1.items.count })")
                        metadataRow("同步狀態") {
                            syncBadge(status: entry.syncStatus)
                        }
                    }
                }
            }
            .padding(AppMetrics.spacingLarge)
        }
        .background(paperBackground.ignoresSafeArea())
        .navigationTitle(entry.word)
        .navigationBarTitleDisplayMode(.inline)
        .navigationDestination(item: $selectedLinkedEntry) { linkedEntry in
            WordDetailSheet(entry: linkedEntry, wrapInNavigation: false)
        }
    }

    private var allForms: [String] {
        var forms: [String] = []
        if let root = entry.rootForm { forms.append(root) }
        forms += entry.inflections.filter { $0 != entry.rootForm }
        return forms
    }

    private var displayedExamples: [String] {
        entry.allReviewExamples
    }

    private var showsSourceContext: Bool {
        let trimmedContext = entry.context.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedContext.isEmpty else { return false }
        return entry.allReviewExamples.first != trimmedContext || entry.bookTitle != "Knowledge Graph"
    }

    private var linkGroups: [LinkGroup] {
        let ordering = ["confusable", "contrasts_with", "shares_usage"]
        let grouped = entry.graphLinksByKind
        return ordering.compactMap { kind in
            guard let items = grouped[kind], !items.isEmpty else { return nil }
            return LinkGroup(id: kind, label: items.first?.label ?? kind, items: items)
        }
    }

    // MARK: - Sections

    private var heroSection: some View {
        AppCard {
            VStack(alignment: .leading, spacing: AppMetrics.spacingMedium) {
                HStack(alignment: .top, spacing: AppMetrics.spacingMedium) {
                    VStack(alignment: .leading, spacing: AppMetrics.spacingSmall) {
                        Text(entry.word)
                            .font(AppFonts.hero(weight: .semibold))
                            .foregroundStyle(.primary)
                            .minimumScaleFactor(0.85)

                        if let pron = entry.pronunciation, !pron.isEmpty {
                            Text("/\(pron)/")
                                .font(AppFonts.subhead())
                                .foregroundStyle(.secondary)
                        }
                    }

                    Spacer(minLength: 12)

                    if let tier = entry.difficultyTier {
                        tierChip(tier)
                    }
                }

                HStack(spacing: AppMetrics.spacingSmall) {
                    if let pos = entry.partOfSpeech {
                        AppTag(text: pos, tone: AppColors.accent(colorScheme))
                    }
                    AppTag(
                        text: entry.reviewMode.localizedTitle,
                        tone: AppColors.translation(colorScheme)
                    )
                }

                Text(entry.translation)
                    .font(AppFonts.h2(weight: .semibold))
                    .foregroundStyle(AppColors.translation(colorScheme))
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.clear)
        }
    }

    private func contentSection<Content: View>(
        title: String,
        systemImage: String,
        tint: Color,
        @ViewBuilder content: () -> Content
    ) -> some View {
        AppCard {
            VStack(alignment: .leading, spacing: AppMetrics.spacingMedium) {
                Label {
                    Text(title)
                        .font(AppFonts.caption(weight: .semibold))
                } icon: {
                    Image(systemName: systemImage)
                }
                .foregroundStyle(tint)

                content()
            }
        }
    }

    @ViewBuilder
    private func graphLinkRow(_ link: KGCardLinkSummary) -> some View {
        if let target = linkedEntry(for: link) {
            Button {
                selectedLinkedEntry = target
            } label: {
                HStack(alignment: .top, spacing: AppMetrics.spacingSmall) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(link.word)
                            .font(AppFonts.subhead(weight: .semibold))
                            .foregroundStyle(.primary)
                            .frame(maxWidth: .infinity, alignment: .leading)

                        Text(link.reason)
                            .font(AppFonts.caption())
                            .foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    Image(systemName: "arrow.up.right")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.tertiary)
                }
                .padding(.vertical, AppMetrics.spacingSmall)
            }
            .buttonStyle(.plain)
        } else {
            VStack(alignment: .leading, spacing: 4) {
                Text(link.word)
                    .font(AppFonts.subhead(weight: .semibold))
                    .foregroundStyle(.primary)
                Text(link.reason)
                    .font(AppFonts.caption())
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, AppMetrics.spacingSmall)
        }
    }

    @ViewBuilder
    private func metadataRow(_ title: String, value: String) -> some View {
        HStack {
            Text(title)
                .font(AppFonts.caption())
                .foregroundStyle(.tertiary)
            Spacer()
            Text(value)
                .font(AppFonts.caption(weight: .medium))
                .foregroundStyle(.secondary)
        }
    }

    @ViewBuilder
    private func metadataRow<Content: View>(_ title: String, @ViewBuilder trailing: () -> Content) -> some View {
        HStack {
            Text(title)
                .font(AppFonts.caption())
                .foregroundStyle(.tertiary)
            Spacer()
            trailing()
        }
    }

    // MARK: - Shared views

    private func tierChip(_ tier: String) -> some View {
        let (color, label) = AppColors.tier(tier, scheme: colorScheme)
        return AppTag(text: label, tone: color)
    }

    @ViewBuilder
    private func syncBadge(status: Int) -> some View {
        switch status {
        case 1:
            Label("已同步", systemImage: "checkmark.circle.fill")
                .font(AppFonts.caption(weight: .medium))
                .foregroundStyle(AppColors.saved(colorScheme))
        case 2:
            Label("同步失敗", systemImage: "exclamationmark.circle.fill")
                .font(AppFonts.caption(weight: .medium))
                .foregroundStyle(AppColors.destructive(colorScheme))
        default:
            Label("待同步", systemImage: "clock")
                .font(AppFonts.caption(weight: .medium))
                .foregroundStyle(.secondary)
        }
    }
}

private extension WordDetailSheet {
    struct LinkGroup: Identifiable {
        let id: String
        let label: String
        let items: [KGCardLinkSummary]
    }

    func linkedEntry(for link: KGCardLinkSummary) -> VocabularyEntry? {
        allEntries.first { $0.kgCardId == link.cardId }
    }
}
