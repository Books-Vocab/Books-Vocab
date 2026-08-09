//
//  ReviewCalendarPresenter.swift
//  Books & Vocab
//
//  完整日曆詳情頁：月曆 + 選中日期的複習紀錄列表。
//

import SwiftUI
import SwiftData

struct ReviewCalendarPresenter: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
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

    private static func formattedMonth(_ date: Date) -> String {
        // template "yMMMM" → en "May 2026" / ja "2026年5月" / ko "2026년 5월"
        LocaleAwareFormatter.shared.string(from: date, template: "yMMMM")
    }

    private static func formattedTime(_ date: Date) -> String {
        LocaleAwareFormatter.shared.string(from: date, format: "HH:mm")
    }

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
                VStack(spacing: appSkin.spacing.sectionGap) {
                    calendarSection
                    if selectedDay != nil {
                        dayDetailSection
                    }
                }
                .padding(.horizontal, appSkin.metrics.pageHorizontalInset)
                .padding(.top, appSkin.metrics.pageTopInset)
                .padding(.bottom, appSkin.metrics.pageBottomInset)
            }
            .vocabCanvasBackground()
            .navigationTitle("學習日曆".localized)
            .inlineNavigationBarTitle()
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("完成".localized) { dismiss() }
                        .font(appSkin.typography.caption)
                }
            }
        }
        .enableInjection()
    }

    // MARK: - Calendar

    private var calendarSection: some View {
        VStack(spacing: appSkin.spacing.inlineGap) {
            // Month navigation
            HStack {
                Button { changeMonth(by: -1) } label: {
                    Image(systemName: "chevron.left")
                        .font(appSkin.typography.iconMedium)
                        .foregroundStyle(appSkin.palette.secondaryText)
                }
                .accessibilityLabel(L10n.string("calendar.month.previous"))

                Spacer()

                Text(Self.formattedMonth(displayedMonth))
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.primaryText)

                Spacer()

                Button { changeMonth(by: 1) } label: {
                    Image(systemName: "chevron.right")
                        .font(appSkin.typography.iconMedium)
                        .foregroundStyle(canGoForward ? appSkin.palette.secondaryText : appSkin.palette.quaternaryText)
                }
                .disabled(!canGoForward)
                .accessibilityLabel(L10n.string("calendar.month.next"))
            }
            .padding(.horizontal, appSkin.spacing.rowMicroGap)

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
        VStack(alignment: .leading, spacing: appSkin.spacing.inlineGap) {
            // Header
            VStack(alignment: .leading, spacing: AppSpacing.microGap) {
                Text(dayDisplayTitle)
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.primaryText)

                if selectedDayRecords.isEmpty {
                    Text("這天沒有複習紀錄".localized)
                        .font(appSkin.typography.caption)
                        .foregroundStyle(appSkin.palette.quaternaryText)
                } else {
                    let s = selectedDaySummary
                    Text(L10n.format("已複習 %@ 張 ・ 記得 %@ ・ 忘記 %@", "\(s.total)", "\(s.remembered)", "\(s.forgot)"))
                        .font(appSkin.typography.caption)
                        .foregroundStyle(appSkin.palette.tertiaryText)
                }
            }

            if !selectedDayRecords.isEmpty {
                VStack(spacing: 0) {
                    ForEach(Array(selectedDayRecords.enumerated()), id: \.element.id) { index, record in
                        if index > 0 {
                            Divider()
                                .foregroundStyle(appSkin.palette.divider)
                                .padding(.leading, AppSpacing.s7 - AppSpacing.s1)
                        }
                        recordRow(record)
                    }
                }
            }
        }
        .vocabCardBackground()
        .animateContentFade(selectedDay)
    }

    private func recordRow(_ record: ReviewRecord) -> some View {
        HStack(spacing: appSkin.spacing.inlineGap) {
            Image(systemName: record.feedback == 1 ? "checkmark" : "xmark")
                .font(appSkin.typography.iconSmall)
                .foregroundStyle(record.feedback == 1 ? appSkin.palette.success : appSkin.palette.destructive)
                .frame(width: 20)

            Text(record.word)
                .font(appSkin.typography.monoBody)
                .foregroundStyle(appSkin.palette.primaryText)
                .lineLimit(1)

            Spacer()

            Text(record.feedback == 1 ? "記得".localized : "忘記".localized)
                .font(appSkin.typography.monoLabel)
                .foregroundStyle(record.feedback == 1 ? appSkin.palette.success : appSkin.palette.destructive)

            Text(Self.formattedTime(record.reviewedAt))
                .font(appSkin.typography.monoLabel)
                .foregroundStyle(appSkin.palette.quaternaryText)
        }
        .padding(.vertical, appSkin.spacing.rowMicroGap)
    }

    // MARK: - Helpers

    private var dayDisplayTitle: String {
        guard let day = selectedDay else { return "" }
        let todayKey = ReviewRecord.makeDayKey(from: Date())
        if day == todayKey { return day + "（今天）".localized }
        return day
    }

    private var canGoForward: Bool {
        let cal = Self.calendar
        let nextMonth = cal.date(byAdding: .month, value: 1, to: displayedMonth) ?? displayedMonth
        let nowComps = cal.dateComponents([.year, .month], from: Date())
        let nextComps = cal.dateComponents([.year, .month], from: nextMonth)
        guard let nextYear = nextComps.year, let nextMonth = nextComps.month,
              let nowYear = nowComps.year, let nowMonth = nowComps.month else { return false }
        return (nextYear, nextMonth) <= (nowYear, nowMonth)
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
