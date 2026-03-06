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
    @Environment(\.modelContext) private var modelContext
    let entry: VocabularyEntry

    private var highlightColor: Color {
        colorScheme == .dark
            ? Color(hue: 48/360, saturation: 0.45, brightness: 0.90).opacity(0.35)
            : Color(hue: 52/360, saturation: 0.65, brightness: 1.00).opacity(0.45)
    }

    private var reviewSnapshot: VocabularyReviewSnapshot {
        entry.reviewSnapshot
    }

    private var paperBackground: Color {
        colorScheme == .dark ? AppColors.paperDark : AppColors.paperLight
    }

    private var heroGradient: LinearGradient {
        LinearGradient(
            colors: [
                AppColors.accent(colorScheme).opacity(colorScheme == .dark ? 0.18 : 0.10),
                AppColors.translation(colorScheme).opacity(colorScheme == .dark ? 0.10 : 0.07),
                Color.clear
            ],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: AppMetrics.spacingLarge) {
                    heroSection
                    reviewSection

                    if !entry.context.isEmpty {
                        contentSection(
                            title: "來源",
                            systemImage: "quote.opening",
                            tint: .secondary
                        ) {
                            VStack(alignment: .leading, spacing: AppMetrics.spacingSmall) {
                                highlightedText(entry.context, isItalic: true)
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
                            highlightedText(explanation, isItalic: false)
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
                            metadataRow("下次複習", value: reviewSnapshot.nextReviewAt.formatted(date: .abbreviated, time: .shortened))
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
                    AppTag(
                        text: reviewSnapshot.isDue ? "該複習" : "穩定中",
                        tone: reviewSnapshot.isDue ? AppColors.translation(colorScheme) : AppColors.saved(colorScheme)
                    )
                }

                Text(entry.translation)
                    .font(AppFonts.h2(weight: .semibold))
                    .foregroundStyle(AppColors.translation(colorScheme))
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(heroGradient)
        }
    }

    private var reviewSection: some View {
        AppCard {
            VStack(alignment: .leading, spacing: AppMetrics.spacingMedium) {
                HStack(alignment: .firstTextBaseline) {
                    Text("複習節奏")
                        .font(AppFonts.h2(weight: .semibold))
                    Spacer()
                    Text(reviewSnapshot.nextReviewAt.reviewRelativeDescription())
                        .font(AppFonts.caption(weight: .semibold))
                        .foregroundStyle(reviewSnapshot.isDue ? AppColors.translation(colorScheme) : .secondary)
                }

                Text(reviewSummaryLine)
                    .font(AppFonts.subhead())
                    .foregroundStyle(.secondary)

                HStack(spacing: AppMetrics.spacingSmall) {
                    reviewMetric(
                        title: "目前間隔",
                        value: intervalLabel(reviewSnapshot.intervalHours),
                        tone: AppColors.accent(colorScheme)
                    )
                    reviewMetric(
                        title: "連續記得",
                        value: "\(reviewSnapshot.streak)",
                        tone: AppColors.saved(colorScheme)
                    )
                    reviewMetric(
                        title: "失誤次數",
                        value: "\(reviewSnapshot.lapseCount)",
                        tone: AppColors.translation(colorScheme)
                    )
                }

                HStack(spacing: AppMetrics.spacingSmall) {
                    reviewButton(
                        title: "忘記了",
                        caption: "縮短間隔",
                        feedback: .forgot,
                        tone: AppColors.translation(colorScheme)
                    )
                    reviewButton(
                        title: "記得",
                        caption: "拉長間隔",
                        feedback: .remembered,
                        tone: AppColors.saved(colorScheme)
                    )
                }
            }
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

    // MARK: - Review UI

    private var reviewSummaryLine: String {
        if reviewSnapshot.reviewCount == 0 {
            return "還沒有複習紀錄。第一次操作後，系統會依照你是否記得自動調整下次時間。"
        }

        let last = reviewSnapshot.lastReviewedAt?.formatted(date: .abbreviated, time: .shortened) ?? "未知"
        return "已複習 \(reviewSnapshot.reviewCount) 次，上次在 \(last)。目前採用簡單倍率法維持節奏。"
    }

    private func intervalLabel(_ hours: Double) -> String {
        if hours >= 24 {
            return String(format: "%.1f 天", hours / 24)
        }
        return String(format: "%.0f 小時", hours)
    }

    private func reviewMetric(title: String, value: String, tone: Color) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(AppFonts.caption())
                .foregroundStyle(.tertiary)
            Text(value)
                .font(AppFonts.subhead(weight: .semibold))
                .foregroundStyle(tone)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, AppMetrics.spacingSmall)
        .padding(.horizontal, AppMetrics.spacingMedium)
        .background(tone.opacity(colorScheme == .dark ? 0.14 : 0.08))
        .clipShape(RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusLarge, style: .continuous))
    }

    private func reviewButton(
        title: String,
        caption: String,
        feedback: ReviewFeedback,
        tone: Color
    ) -> some View {
        Button {
            withAnimation(.spring(response: 0.35, dampingFraction: 0.82)) {
                entry.applyReviewFeedback(feedback)
                try? modelContext.save()
            }
        } label: {
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(AppFonts.subhead(weight: .semibold))
                Text(caption)
                    .font(AppFonts.caption())
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, AppMetrics.spacingMedium)
            .padding(.horizontal, AppMetrics.spacingMedium)
            .background(tone.opacity(colorScheme == .dark ? 0.18 : 0.10))
            .overlay(
                RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusLarge, style: .continuous)
                    .stroke(tone.opacity(0.12), lineWidth: 0.8)
            )
            .clipShape(RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusLarge, style: .continuous))
        }
        .buttonStyle(.plain)
        .foregroundStyle(tone)
    }

    // MARK: - Shared views

    private func tierChip(_ tier: String) -> some View {
        let (color, label) = AppColors.tier(tier, scheme: colorScheme)
        return AppTag(text: label, tone: color)
    }

    private static let highlightPattern = try! NSRegularExpression(pattern: #"\*\*(.+?)\*\*|`(.+?)`"#)

    private func highlightedText(_ raw: String, isItalic: Bool) -> Text {
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
                highlighted.backgroundColor = highlightColor
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
