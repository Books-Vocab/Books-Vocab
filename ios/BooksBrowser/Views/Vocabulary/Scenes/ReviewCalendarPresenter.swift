//
//  ReviewCalendarPresenter.swift
//  BooksBrowser
//
//  完整日曆詳情頁：月曆 + 選中日期的複習紀錄列表。
//

import SwiftUI
import SwiftData

struct ReviewCalendarPresenter: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.dismiss) private var dismiss

    @Query var allRecords: [ReviewRecord]

    private static let sixMonthsAgo = Calendar.current.date(byAdding: .month, value: -6, to: Date()) ?? Date()

    init() {
        let cutoff = Self.sixMonthsAgo
        _allRecords = Query(
            filter: #Predicate<ReviewRecord> { $0.reviewedAt > cutoff },
            sort: \ReviewRecord.reviewedAt,
            order: .reverse
        )
    }

    @State private var displayedMonth: Date = Date()
    @State private var selectedDay: String? = ReviewRecord.makeDayKey(from: Date())

    private static let calendar = Calendar.current

    private static let monthFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy 年 M 月"
        f.locale = Locale(identifier: "zh_TW")
        return f
    }()

    private static let timeFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm"
        return f
    }()

    private var activityMap: [String: Int] {
        ReviewActivityLog.activity(for: 365, records: allRecords)
    }

    private var selectedDayRecords: [ReviewRecord] {
        guard let day = selectedDay else { return [] }
        return ReviewActivityLog.recordsForDay(day, from: allRecords)
    }

    private var selectedDaySummary: (total: Int, remembered: Int, forgot: Int) {
        let records = selectedDayRecords
        let remembered = records.filter { $0.feedback == 1 }.count
        return (records.count, remembered, records.count - remembered)
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: vocabSkin.spacing.sectionGap) {
                    calendarSection
                    if let _ = selectedDay {
                        dayDetailSection
                    }
                }
                .padding(.horizontal, vocabSkin.metrics.pageHorizontalInset)
                .padding(.top, vocabSkin.metrics.pageTopInset)
                .padding(.bottom, vocabSkin.metrics.pageBottomInset)
            }
            .vocabCanvasBackground()
            .navigationTitle("學習日曆".localized)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成".localized) { dismiss() }
                        .font(vocabSkin.typography.captionStrong)
                }
            }
        }
    }

    // MARK: - Calendar

    private var calendarSection: some View {
        VStack(spacing: vocabSkin.spacing.inlineGap) {
            // Month navigation
            HStack {
                Button { changeMonth(by: -1) } label: {
                    Image(systemName: "chevron.left")
                        .font(vocabSkin.typography.iconMedium)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                }

                Spacer()

                Text(Self.monthFormatter.string(from: displayedMonth))
                    .font(vocabSkin.typography.captionStrong)
                    .foregroundStyle(vocabSkin.palette.primaryText)

                Spacer()

                Button { changeMonth(by: 1) } label: {
                    Image(systemName: "chevron.right")
                        .font(vocabSkin.typography.iconMedium)
                        .foregroundStyle(canGoForward ? vocabSkin.palette.secondaryText : vocabSkin.palette.quaternaryText)
                }
                .disabled(!canGoForward)
            }
            .padding(.horizontal, vocabSkin.spacing.microGap)

            VocabCalendarGrid(
                displayedMonth: displayedMonth,
                activityMap: activityMap,
                selectedDay: $selectedDay
            )
        }
        .vocabCardBackground()
    }

    // MARK: - Day Detail

    private var dayDetailSection: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.inlineGap) {
            // Header
            VStack(alignment: .leading, spacing: 2) {
                Text(dayDisplayTitle)
                    .font(vocabSkin.typography.captionStrong)
                    .foregroundStyle(vocabSkin.palette.primaryText)

                if selectedDayRecords.isEmpty {
                    Text("這天沒有複習紀錄".localized)
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.quaternaryText)
                } else {
                    let s = selectedDaySummary
                    Text(L10n.format("已複習 %@ 張 ・ 記得 %@ ・ 忘記 %@", "\(s.total)", "\(s.remembered)", "\(s.forgot)"))
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.tertiaryText)
                }
            }

            if !selectedDayRecords.isEmpty {
                let (local, syncCount) = partitionedRecords
                VStack(spacing: 0) {
                    ForEach(Array(local.enumerated()), id: \.element.id) { index, record in
                        if index > 0 {
                            Divider()
                                .foregroundStyle(vocabSkin.palette.divider)
                                .padding(.leading, 28)
                        }
                        recordRow(record)
                    }

                    if syncCount > 0 {
                        if !local.isEmpty {
                            Divider()
                                .foregroundStyle(vocabSkin.palette.divider)
                                .padding(.leading, 28)
                        }
                        syncPlaceholderRow(count: syncCount)
                    }
                }
            }
        }
        .vocabCardBackground()
        .animation(AppMotion.contentFade, value: selectedDay)
    }

    private var partitionedRecords: (local: [ReviewRecord], syncCount: Int) {
        var local: [ReviewRecord] = []
        var syncCount = 0
        for record in selectedDayRecords {
            if record.entryID == nil {
                syncCount += 1
            } else {
                local.append(record)
            }
        }
        return (local, syncCount)
    }

    private func syncPlaceholderRow(count: Int) -> some View {
        HStack(spacing: vocabSkin.spacing.inlineGap) {
            Image(systemName: "arrow.triangle.2.circlepath")
                .font(vocabSkin.typography.iconSmall)
                .foregroundStyle(vocabSkin.palette.quaternaryText)
                .frame(width: 20)

            Text(L10n.format("另有 %@ 筆來自其他裝置", "\(count)"))
                .font(vocabSkin.typography.caption)
                .foregroundStyle(vocabSkin.palette.quaternaryText)

            Spacer()
        }
        .padding(.vertical, vocabSkin.spacing.microGap)
    }

    private func recordRow(_ record: ReviewRecord) -> some View {
        HStack(spacing: vocabSkin.spacing.inlineGap) {
            Image(systemName: record.feedback == 1 ? "checkmark" : "xmark")
                .font(vocabSkin.typography.iconSmall)
                .foregroundStyle(record.feedback == 1 ? vocabSkin.palette.success : vocabSkin.palette.destructive)
                .frame(width: 20)

            Text(record.word)
                .font(vocabSkin.typography.monoBody)
                .foregroundStyle(vocabSkin.palette.primaryText)
                .lineLimit(1)

            Spacer()

            Text(record.feedback == 1 ? "記得".localized : "忘記".localized)
                .font(vocabSkin.typography.monoLabel)
                .foregroundStyle(record.feedback == 1 ? vocabSkin.palette.success : vocabSkin.palette.destructive)

            Text(Self.timeFormatter.string(from: record.reviewedAt))
                .font(vocabSkin.typography.monoLabel)
                .foregroundStyle(vocabSkin.palette.quaternaryText)
        }
        .padding(.vertical, vocabSkin.spacing.microGap)
    }

    // MARK: - Helpers

    private var dayDisplayTitle: String {
        guard let day = selectedDay else { return "" }
        let todayKey = ReviewRecord.makeDayKey(from: Date())
        if day == todayKey { return "\(day)" + "（今天）".localized }
        return day
    }

    private var canGoForward: Bool {
        let cal = Self.calendar
        let nextMonth = cal.date(byAdding: .month, value: 1, to: displayedMonth) ?? displayedMonth
        let nowComps = cal.dateComponents([.year, .month], from: Date())
        let nextComps = cal.dateComponents([.year, .month], from: nextMonth)
        return (nextComps.year!, nextComps.month!) <= (nowComps.year!, nowComps.month!)
    }

    private func changeMonth(by offset: Int) {
        withAnimation(AppMotion.phaseChange) {
            displayedMonth = Self.calendar.date(
                byAdding: .month, value: offset, to: displayedMonth
            ) ?? displayedMonth
            selectedDay = nil
        }
    }
}
