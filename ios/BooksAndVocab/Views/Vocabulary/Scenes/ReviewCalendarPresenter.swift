//
//  ReviewCalendarPresenter.swift
//  Books & Vocab
//
//  完整日曆詳情頁：月曆 + 選中日期的複習紀錄列表。
//

import SwiftUI
import SwiftData

struct ReviewCalendarClock: Equatable {
    let now: Date
    let timeZone: TimeZone

    var calendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        return calendar
    }

    init(now: Date, timeZone: TimeZone) {
        self.now = now
        self.timeZone = timeZone
    }

    func dayKey(for date: Date) -> String {
        LocaleAwareFormatter.shared.machineDayKey(from: date, timeZone: timeZone)
    }
}

enum ReviewCalendarPresentation {
    enum DayState: Equatable {
        case empty
        case populated(total: Int, remembered: Int, forgot: Int)
    }

    static func filteredRecords(_ records: [ReviewRecord], filter: NotebookFilter) -> [ReviewRecord] {
        filter.isFiltered ? records.filter { filter.matches($0.notebookId) } : records
    }

    static func dayKey(for date: Date, clock: ReviewCalendarClock) -> String {
        clock.dayKey(for: date)
    }

    static func records(
        for dayKey: String,
        from records: [ReviewRecord],
        clock: ReviewCalendarClock
    ) -> [ReviewRecord] {
        records
            .filter { clock.dayKey(for: $0.reviewedAt) == dayKey }
            .sorted { $0.reviewedAt > $1.reviewedAt }
    }

    static func activity(
        for days: Int = 365,
        records: [ReviewRecord],
        clock: ReviewCalendarClock
    ) -> [String: Int] {
        let cutoff = clock.calendar.date(byAdding: .day, value: -days, to: clock.now) ?? clock.now
        var result: [String: Int] = [:]
        for record in records where record.reviewedAt >= cutoff {
            result[clock.dayKey(for: record.reviewedAt), default: 0] += 1
        }
        return result
    }

    static func dayState(for records: [ReviewRecord]) -> DayState {
        guard !records.isEmpty else { return .empty }
        let remembered = records.filter { $0.feedback == 1 }.count
        return .populated(
            total: records.count,
            remembered: remembered,
            forgot: records.count - remembered
        )
    }
}

struct ReviewCalendarPresenter: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    @Environment(\.dismiss) private var dismiss

    let filter: NotebookFilter
    let clock: ReviewCalendarClock
    @Query var allRecords: [ReviewRecord]

    init(filter: NotebookFilter = NotebookFilter(), clock: ReviewCalendarClock) {
        self.filter = filter
        self.clock = clock
        let cutoff = clock.calendar.date(byAdding: .month, value: -6, to: clock.now) ?? clock.now
        _allRecords = Query(
            filter: #Predicate<ReviewRecord> { $0.reviewedAt > cutoff },
            sort: \ReviewRecord.reviewedAt,
            order: .reverse
        )
        _displayedMonth = State(initialValue: clock.now)
        _selectedDay = State(initialValue: clock.dayKey(for: clock.now))
    }

    @State private var displayedMonth: Date
    @State private var selectedDay: String?

    private static func formattedMonth(_ date: Date, clock: ReviewCalendarClock) -> String {
        // template "yMMMM" → en "May 2026" / ja "2026年5月" / ko "2026년 5월"
        LocaleAwareFormatter.shared.string(from: date, template: "yMMMM", timeZone: clock.timeZone)
    }

    private var activityMap: [String: Int] {
        ReviewCalendarPresentation.activity(for: 365, records: filteredRecords, clock: clock)
    }

    private var filteredRecords: [ReviewRecord] {
        ReviewCalendarPresentation.filteredRecords(allRecords, filter: filter)
    }

    private var selectedDayRecords: [ReviewRecord] {
        guard let day = selectedDay else { return [] }
        return ReviewCalendarPresentation.records(for: day, from: filteredRecords, clock: clock)
    }

    private var selectedDaySummary: (total: Int, remembered: Int, forgot: Int) {
        switch ReviewCalendarPresentation.dayState(for: selectedDayRecords) {
        case .empty:
            return (0, 0, 0)
        case let .populated(total, remembered, forgot):
            return (total, remembered, forgot)
        }
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

                Text(Self.formattedMonth(displayedMonth, clock: clock))
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
                selectedDay: $selectedDay,
                clock: clock
            )
        }
        .vocabCardBackground()
    }

    // MARK: - Day Detail

    private var dayDetailSection: some View {
        Group {
            if case .empty = ReviewCalendarPresentation.dayState(for: selectedDayRecords) {
                VocabStateMessageCard(
                    title: dayDisplayTitle,
                    systemImage: "calendar.badge.exclamationmark",
                    description: "這天沒有複習紀錄".localized
                )
                .accessibilityIdentifier("reviewCalendar.emptyDay")
            } else {
                populatedDayDetailSection
            }
        }
        .animateContentFade(selectedDay)
    }

    private var populatedDayDetailSection: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.inlineGap) {
            VStack(alignment: .leading, spacing: AppSpacing.microGap) {
                Text(dayDisplayTitle)
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.primaryText)

                let s = selectedDaySummary
                Text(L10n.format("已複習 %@ 張 ・ 記得 %@ ・ 忘記 %@", "\(s.total)", "\(s.remembered)", "\(s.forgot)"))
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.tertiaryText)
            }

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
        .vocabCardBackground()
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

            Text(LocaleAwareFormatter.shared.string(
                from: record.reviewedAt,
                format: "HH:mm",
                timeZone: clock.timeZone
            ))
                .font(appSkin.typography.monoLabel)
                .foregroundStyle(appSkin.palette.quaternaryText)
        }
        .padding(.vertical, appSkin.spacing.rowMicroGap)
    }

    // MARK: - Helpers

    private var dayDisplayTitle: String {
        guard let day = selectedDay else { return "" }
        let todayKey = clock.dayKey(for: clock.now)
        if day == todayKey { return day + "（今天）".localized }
        return day
    }

    private var canGoForward: Bool {
        let cal = clock.calendar
        let nextMonth = cal.date(byAdding: .month, value: 1, to: displayedMonth) ?? displayedMonth
        let nowComps = cal.dateComponents([.year, .month], from: clock.now)
        let nextComps = cal.dateComponents([.year, .month], from: nextMonth)
        guard let nextYear = nextComps.year, let nextMonth = nextComps.month,
              let nowYear = nowComps.year, let nowMonth = nowComps.month else { return false }
        return (nextYear, nextMonth) <= (nowYear, nowMonth)
    }

    private func changeMonth(by offset: Int) {
        withAnimation(AppMotion.phaseChange) {
            displayedMonth = clock.calendar.date(
                byAdding: .month, value: offset, to: displayedMonth
            ) ?? displayedMonth
            selectedDay = nil
        }
    }
}
