//
//  WordDetailSheet.swift
//  BooksBrowser
//
//  單字詳情 Sheet — VocabularyListView 與 KGVocabView 共用
//

import SwiftUI
import Foundation

struct WordDetailSheet: View {
    @Environment(\.colorScheme) private var colorScheme
    let entry: VocabularyEntry

    private var paperBackground: Color {
        colorScheme == .dark ? AppColors.paperDark : AppColors.paperLight
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: AppMetrics.spacingLarge) {
                    heroSection

                    if !entry.context.isEmpty {
                        contentSection(
                            title: "來源",
                            systemImage: "quote.opening",
                            tint: .secondary
                        ) {
                            VStack(alignment: .leading, spacing: AppMetrics.spacingSmall) {
                                highlightedText(
                                    entry.context,
                                    isItalic: true,
                                    emphasis: .source
                                )
                                    .font(AppFonts.body())
                                    .foregroundStyle(.secondary)

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
                            highlightedText(
                                explanation,
                                isItalic: false,
                                emphasis: .note
                            )
                                .font(AppFonts.body())
                                .foregroundStyle(.primary)
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

                    contentSection(
                        title: "卡片資訊",
                        systemImage: "tray.full",
                        tint: .secondary
                    ) {
                        VStack(spacing: AppMetrics.spacingSmall) {
                            metadataRow("加入日期", value: entry.dateAdded.formatted(date: .abbreviated, time: .omitted))
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
        }
    }

    private var allForms: [String] {
        var forms: [String] = []
        if let root = entry.rootForm { forms.append(root) }
        forms += entry.inflections.filter { $0 != entry.rootForm }
        return forms
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

    private static let highlightPattern = try! NSRegularExpression(pattern: #"\*\*(.+?)\*\*|`(.+?)`"#)

    private enum TextEmphasis {
        case source
        case note
    }

    private func highlightedText(
        _ raw: String,
        isItalic: Bool,
        emphasis: TextEmphasis
    ) -> Text {
        let nsString = raw as NSString
        let matches = Self.highlightPattern.matches(in: raw, range: NSRange(location: 0, length: nsString.length))
        let baseFont: Font = isItalic ? .body.italic() : .body

        var result = AttributedString()
        var lastEnd = 0

        for match in matches {
            let beforeRange = NSRange(location: lastEnd, length: match.range.location - lastEnd)
            if beforeRange.length > 0 {
                var part = AttributedString(nsString.substring(with: beforeRange))
                part.font = baseFont
                result += part
            }

            let g1 = match.range(at: 1)
            let g2 = match.range(at: 2)
            let captureRange = g1.location != NSNotFound ? g1 : g2

            if captureRange.location != NSNotFound, captureRange.length > 0 {
                var highlighted = AttributedString(nsString.substring(with: captureRange))
                highlighted.font = baseFont
                switch emphasis {
                case .source:
                    highlighted.foregroundColor = .primary
                    highlighted.underlineStyle = .single
                case .note:
                    highlighted.foregroundColor = .primary
                    highlighted.underlineStyle = .single
                }
                result += highlighted
            }

            lastEnd = match.range.location + match.range.length
        }

        if lastEnd < nsString.length {
            var tail = AttributedString(nsString.substring(from: lastEnd))
            tail.font = baseFont
            result += tail
        }

        return Text(result)
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
