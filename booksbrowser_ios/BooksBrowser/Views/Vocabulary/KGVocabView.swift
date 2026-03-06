//
//  KGVocabView.swift
//  BooksBrowser
//
//  Displays vocabulary cards fetched from the Knowledge Graph API server.
//

import SwiftUI
import SwiftData

struct KGVocabView: View {
    @Environment(\.modelContext) private var modelContext
    @Environment(\.kgService) private var kgService
    @Binding var searchText: String

    @Query private var syncedEntries: [VocabularyEntry]
    @Environment(\.authManager) private var authManager

    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var selectedEntry: VocabularyEntry?
    @State private var selectedReviewState: VocabularyReviewState = .due
    @State private var showTodayReview = false

    @Query(filter: #Predicate<VocabularyEntry> { $0.actionType == "delete" })
    private var pendingDeletes: [VocabularyEntry]

    init(searchText: Binding<String>) {
        self._searchText = searchText
        let filter = #Predicate<VocabularyEntry> { $0.syncStatus == 1 && $0.actionType != "delete" }
        self._syncedEntries = Query(filter: filter)
    }

    var body: some View {
        Group {
            if !authManager.isLoggedIn {
                ContentUnavailableView(
                    "尚未登入",
                    systemImage: "person.crop.circle.badge.exclamationmark",
                    description: Text("登入後，您在閱讀時標記的生詞將會自動整理於此。")
                )
            } else if isLoading && syncedEntries.isEmpty {
                ProgressView("載入知識庫...")
            } else {
                content
            }
        }
        .sheet(item: $selectedEntry) { entry in
            WordDetailSheet(entry: entry)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
        .fullScreenCover(isPresented: $showTodayReview) {
            TodayReviewView(entries: todaySessionEntries)
        }
        .task {
            guard authManager.isLoggedIn else { return }

            isLoading = true
            do {
                try await kgService.pullCardsToLocal(container: modelContext.container, progress: nil)
                errorMessage = nil
                if dueEntries.isEmpty && !unlearnedEntries.isEmpty {
                    selectedReviewState = .unlearned
                }
            } catch {
                errorMessage = error.localizedDescription
            }
            isLoading = false
        }
    }

    private var content: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: AppMetrics.spacingLarge) {
                if !pendingDeletes.isEmpty {
                    ErrorBannerView(
                        message: "\(pendingDeletes.count) 個單字刪除待同步",
                        onDismiss: nil,
                        onRetry: { Task { await retryPendingDeletes() } }
                    )
                } else if let error = errorMessage {
                    ErrorBannerView(message: "離線模式，同步失敗：\(error)", onDismiss: {
                        errorMessage = nil
                    })
                }

                if !syncedEntries.isEmpty {
                    todayReviewHero
                    stateSection
                    browserSection
                } else {
                    emptyState
                }
            }
            .padding(AppMetrics.spacingLarge)
            .padding(.bottom, 120)
        }
    }

    private var todayReviewHero: some View {
        Button {
            showTodayReview = true
        } label: {
            AppCard(padding: 0) {
                ZStack(alignment: .topLeading) {
                    RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusExtraLarge, style: .continuous)
                        .fill(
                            LinearGradient(
                                colors: [
                                    AppColors.translation(.light).opacity(0.16),
                                    AppColors.accent(.light).opacity(0.12),
                                    Color.white.opacity(0.82)
                                ],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                            )
                        )

                    VStack(alignment: .leading, spacing: AppMetrics.spacingMedium) {
                        HStack(alignment: .top) {
                            VStack(alignment: .leading, spacing: 8) {
                                Text("Today Review")
                                    .font(AppFonts.caption(weight: .semibold))
                                    .foregroundStyle(.secondary)

                                Text("今日待複習")
                                    .font(AppFonts.hero(weight: .semibold))
                                    .foregroundStyle(.primary)

                                Text(heroDescription)
                                    .font(AppFonts.subhead())
                                    .foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }

                            Spacer(minLength: 12)

                            VStack(alignment: .trailing, spacing: 2) {
                                Text("\(todaySessionEntries.count)")
                                    .font(.system(size: 58, weight: .semibold, design: .serif))
                                    .foregroundStyle(todaySessionEntries.isEmpty ? .secondary : .primary)
                                Text("cards")
                                    .font(AppFonts.caption(weight: .semibold))
                                    .foregroundStyle(.tertiary)
                            }
                        }

                        HStack(spacing: AppMetrics.spacingSmall) {
                            sessionStat(title: "待複習", value: "\(dueEntries.count)", tone: AppColors.translation(.light))
                            sessionStat(title: "未學習", value: "\(unlearnedEntries.count)", tone: AppColors.accent(.light))
                            sessionStat(title: "已複習", value: "\(reviewedEntries.count)", tone: AppColors.saved(.light))
                        }

                        HStack(spacing: AppMetrics.spacingSmall) {
                            Label("flashcards", systemImage: "rectangle.stack")
                                .font(AppFonts.caption(weight: .semibold))
                                .foregroundStyle(.secondary)

                            Spacer()

                            Text(todaySessionEntries.isEmpty ? "暫無 session" : "開始複習")
                                .font(AppFonts.subhead(weight: .semibold))
                                .foregroundStyle(todaySessionEntries.isEmpty ? .secondary : .primary)

                            Image(systemName: "arrow.right.circle.fill")
                                .font(.title3)
                                .foregroundStyle(todaySessionEntries.isEmpty ? .secondary : AppColors.translation(.light))
                        }
                        .padding(.top, 4)
                    }
                    .padding(AppMetrics.spacingLarge)
                }
            }
        }
        .buttonStyle(.plain)
        .disabled(todaySessionEntries.isEmpty)
    }

    private var stateSection: some View {
        AppCard {
            VStack(alignment: .leading, spacing: AppMetrics.spacingMedium) {
                Text("知識庫狀態")
                    .font(AppFonts.caption(weight: .semibold))
                    .foregroundStyle(.secondary)

                Picker("", selection: $selectedReviewState) {
                    ForEach(VocabularyReviewState.allCases) { state in
                        Text("\(state.title) \(count(for: state))").tag(state)
                    }
                }
                .pickerStyle(.segmented)

                Text(stateDescription)
                    .font(AppFonts.subhead())
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var browserSection: some View {
        AppCard {
            VStack(alignment: .leading, spacing: AppMetrics.spacingMedium) {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(selectedReviewState.title)
                            .font(AppFonts.h2(weight: .semibold))
                            .foregroundStyle(.primary)
                        Text("\(filteredEntries.count) 張卡片")
                            .font(AppFonts.caption(weight: .semibold))
                            .foregroundStyle(.tertiary)
                    }
                    Spacer()
                }

                if filteredEntries.isEmpty {
                    emptyState
                } else {
                    LazyVStack(spacing: 0) {
                        ForEach(Array(filteredEntries.enumerated()), id: \.element.id) { index, entry in
                            WordRow(
                                word: entry.word,
                                translation: entry.translation,
                                partOfSpeech: entry.partOfSpeech,
                                difficultyTier: entry.difficultyTier,
                                bookTitle: nil,
                                chapterTitle: nil,
                                nextReviewAt: entry.nextReviewAt,
                                reviewState: entry.reviewState,
                                syncStatus: nil
                            )
                            .contentShape(Rectangle())
                            .onTapGesture { selectedEntry = entry }
                            .contextMenu {
                                Button(role: .destructive) {
                                    markForDeletion(entry)
                                } label: {
                                    Label("刪除卡片", systemImage: "trash")
                                }
                            }

                            if index < filteredEntries.count - 1 {
                                Divider()
                                    .padding(.vertical, AppMetrics.spacingMedium)
                            }
                        }
                    }
                }
            }
        }
    }

    private var heroDescription: String {
        if todaySessionEntries.isEmpty {
            return "今天沒有待複習或未學習卡片。"
        }
        return "把到期卡與新卡一起拉進同一個 session，用 flashcards 節奏完成今天的複習。"
    }

    private var stateDescription: String {
        switch selectedReviewState {
        case .unlearned:
            return "這些卡片已進知識庫，但還沒真正開始複習。"
        case .due:
            return "今天應該先處理的卡片，會優先進入每日 session。"
        case .reviewed:
            return "今天已處理完或尚未到期的卡片。"
        }
    }

    private var dueEntries: [VocabularyEntry] {
        sortedEntries.filter { $0.reviewState == .due }
    }

    private var unlearnedEntries: [VocabularyEntry] {
        sortedEntries.filter { $0.reviewState == .unlearned }
    }

    private var reviewedEntries: [VocabularyEntry] {
        sortedEntries.filter { $0.reviewState == .reviewed }
    }

    private var todaySessionEntries: [VocabularyEntry] {
        dueEntries + unlearnedEntries
    }

    private var filteredEntries: [VocabularyEntry] {
        let stateFiltered = sortedEntries.filter { $0.reviewState == selectedReviewState }
        guard !searchText.isEmpty else { return stateFiltered }
        return stateFiltered.filter {
            $0.word.localizedCaseInsensitiveContains(searchText) ||
            $0.translation.localizedCaseInsensitiveContains(searchText)
        }
    }

    private var sortedEntries: [VocabularyEntry] {
        syncedEntries.sorted {
            if reviewOrder($0.reviewState) != reviewOrder($1.reviewState) {
                return reviewOrder($0.reviewState) < reviewOrder($1.reviewState)
            }
            if $0.reviewState != .reviewed && $0.nextReviewAt != $1.nextReviewAt {
                return $0.nextReviewAt < $1.nextReviewAt
            }
            let t0 = tierOrder($0.difficultyTier)
            let t1 = tierOrder($1.difficultyTier)
            if t0 != t1 { return t0 < t1 }
            return $0.word.localizedCaseInsensitiveCompare($1.word) == .orderedAscending
        }
    }

    private var emptyState: some View {
        ContentUnavailableView {
            Label(emptyStateTitle, systemImage: emptyStateIcon)
        } description: {
            Text(emptyStateDescription)
        }
    }

    private var emptyStateTitle: String {
        if syncedEntries.isEmpty {
            return "知識庫目前是空的"
        }
        if !searchText.isEmpty {
            return "沒有符合的單字"
        }
        return selectedReviewState.title
    }

    private var emptyStateDescription: String {
        if syncedEntries.isEmpty {
            return "同步完成後，這裡會顯示你的雲端單字。"
        }
        if !searchText.isEmpty {
            return "試試其他關鍵字，或切換到別的狀態。"
        }
        switch selectedReviewState {
        case .unlearned:
            return "目前沒有尚未進入複習流程的卡片。"
        case .due:
            return "今天沒有到期卡片。"
        case .reviewed:
            return "目前沒有已複習中的卡片。"
        }
    }

    private var emptyStateIcon: String {
        switch selectedReviewState {
        case .unlearned: return "sparkles"
        case .due: return "checkmark.seal"
        case .reviewed: return "leaf"
        }
    }

    private func sessionStat(title: String, value: String, tone: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(AppFonts.caption())
                .foregroundStyle(.secondary)
            Text(value)
                .font(AppFonts.h2(weight: .semibold))
                .foregroundStyle(tone)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, AppMetrics.spacingSmall)
        .padding(.horizontal, AppMetrics.spacingMedium)
        .background(Color.white.opacity(0.48))
        .clipShape(RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusLarge, style: .continuous))
    }

    private func count(for state: VocabularyReviewState) -> Int {
        syncedEntries.filter { $0.reviewState == state }.count
    }

    private func reviewOrder(_ state: VocabularyReviewState) -> Int {
        switch state {
        case .due: return 0
        case .unlearned: return 1
        case .reviewed: return 2
        }
    }

    private func tierOrder(_ tier: String?) -> Int {
        switch tier {
        case "core": return 0
        case "intermediate": return 1
        case "advanced": return 2
        case "rare": return 3
        default: return 4
        }
    }

    private func markForDeletion(_ entry: VocabularyEntry) {
        entry.actionType = "delete"
        entry.syncStatus = 0
        try? modelContext.save()
    }

    private func retryPendingDeletes() async {
        for entry in pendingDeletes {
            do {
                try await kgService.deleteCard(word: entry.word)
                modelContext.delete(entry)
            } catch {
            }
        }
        try? modelContext.save()
        await kgService.healthCheck()
    }
}

private struct TodayReviewView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.modelContext) private var modelContext
    @State private var queue: [VocabularyEntry]
    @State private var currentIndex = 0
    @State private var showBack = false

    init(entries: [VocabularyEntry]) {
        _queue = State(initialValue: entries)
    }

    var body: some View {
        NavigationStack {
            Group {
                if let current = currentEntry {
                    VStack(spacing: AppMetrics.spacingLarge) {
                        HStack {
                            Text(progressText)
                                .font(AppFonts.caption(weight: .semibold))
                                .foregroundStyle(.secondary)
                            Spacer()
                            Text(showBack ? "背面" : "正面")
                                .font(AppFonts.caption(weight: .semibold))
                                .foregroundStyle(.tertiary)
                        }
                        .padding(.horizontal, AppMetrics.spacingLarge)

                        Button {
                            withAnimation(.spring(response: 0.45, dampingFraction: 0.82)) {
                                showBack.toggle()
                            }
                        } label: {
                            AppCard(padding: 0) {
                                ZStack {
                                    RoundedRectangle(cornerRadius: 30, style: .continuous)
                                        .fill(
                                            LinearGradient(
                                                colors: [
                                                    Color.white.opacity(0.96),
                                                    AppColors.accent(.light).opacity(showBack ? 0.10 : 0.05)
                                                ],
                                                startPoint: .topLeading,
                                                endPoint: .bottomTrailing
                                            )
                                        )

                                    VStack(alignment: .leading, spacing: AppMetrics.spacingLarge) {
                                        if showBack {
                                            VStack(alignment: .leading, spacing: AppMetrics.spacingMedium) {
                                                Text(current.word)
                                                    .font(AppFonts.h2(weight: .semibold))
                                                    .foregroundStyle(.secondary)
                                                Text(current.translation)
                                                    .font(AppFonts.hero(weight: .semibold))
                                                    .foregroundStyle(AppColors.translation(.light))

                                                if !current.context.isEmpty {
                                                    Text(current.context)
                                                        .font(AppFonts.body())
                                                        .foregroundStyle(.secondary)
                                                        .italic()
                                                        .lineLimit(5)
                                                }
                                            }
                                        } else {
                                            VStack(alignment: .leading, spacing: AppMetrics.spacingMedium) {
                                                if let pos = current.partOfSpeech {
                                                    AppTag(text: pos, tone: AppColors.accent(.light))
                                                }
                                                Spacer(minLength: 0)
                                                Text(current.word)
                                                    .font(.system(size: 48, weight: .semibold, design: .serif))
                                                    .foregroundStyle(.primary)
                                                Text("先想意思，再點卡片翻面")
                                                    .font(AppFonts.subhead())
                                                    .foregroundStyle(.secondary)
                                            }
                                        }

                                        Spacer()

                                        HStack {
                                            Label(showBack ? "點擊回正面" : "點擊看答案", systemImage: "rectangle.portrait.on.rectangle.portrait")
                                                .font(AppFonts.caption(weight: .semibold))
                                                .foregroundStyle(.tertiary)
                                            Spacer()
                                        }
                                    }
                                    .padding(28)
                                }
                                .frame(minHeight: 420)
                            }
                            .rotation3DEffect(
                                .degrees(showBack ? 180 : 0),
                                axis: (x: 0, y: 1, z: 0)
                            )
                        }
                        .buttonStyle(.plain)
                        .padding(.horizontal, AppMetrics.spacingLarge)

                        if showBack {
                            HStack(spacing: AppMetrics.spacingSmall) {
                                reviewButton(
                                    title: "忘記了",
                                    caption: "縮短間隔",
                                    tone: AppColors.translation(.light)
                                ) {
                                    submit(.forgot)
                                }
                                reviewButton(
                                    title: "記得",
                                    caption: "進入下一張",
                                    tone: AppColors.saved(.light)
                                ) {
                                    submit(.remembered)
                                }
                            }
                            .padding(.horizontal, AppMetrics.spacingLarge)
                        } else {
                            Text("先翻面，再做記憶判斷。")
                                .font(AppFonts.caption())
                                .foregroundStyle(.secondary)
                        }

                        Spacer()
                    }
                    .padding(.top, AppMetrics.spacingLarge)
                } else {
                    ContentUnavailableView(
                        "今天複習完成",
                        systemImage: "checkmark.circle",
                        description: Text("待複習與未學習卡片都處理完了。")
                    )
                }
            }
            .navigationTitle("今日複習")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("關閉") { dismiss() }
                }
            }
            .background(Color(.systemGroupedBackground).ignoresSafeArea())
        }
    }

    private var currentEntry: VocabularyEntry? {
        guard currentIndex < queue.count else { return nil }
        return queue[currentIndex]
    }

    private var progressText: String {
        "\(min(currentIndex + 1, queue.count)) / \(queue.count)"
    }

    private func submit(_ feedback: ReviewFeedback) {
        guard let current = currentEntry else { return }
        current.applyReviewFeedback(feedback)
        try? modelContext.save()
        showBack = false
        currentIndex += 1
    }

    private func reviewButton(
        title: String,
        caption: String,
        tone: Color,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(AppFonts.h2(weight: .semibold))
                Text(caption)
                    .font(AppFonts.caption())
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, AppMetrics.spacingLarge)
            .padding(.horizontal, AppMetrics.spacingMedium)
            .background(tone.opacity(0.10))
            .overlay(
                RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusLarge, style: .continuous)
                    .stroke(tone.opacity(0.12), lineWidth: 0.8)
            )
            .clipShape(RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusLarge, style: .continuous))
        }
        .buttonStyle(.plain)
        .foregroundStyle(tone)
    }
}
