//
//  VocabularyListView.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/24.
//

import SwiftUI
import SwiftData
import UniformTypeIdentifiers

/// 生詞庫列表
struct VocabularyListView: View {
    @Query(sort: \VocabularyEntry.dateAdded, order: .reverse) private var allEntries: [VocabularyEntry]
    @Environment(\.modelContext) private var modelContext
    @Environment(\.vocabSkin) private var vocabSkin

    @State private var searchText = ""
    @State private var showExportSheet = false
    @State private var showSyncView = false
    @State private var showSettings = false
    @State private var exportURL: URL?
    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager
    @State private var selectedTab = 0  // 0 = 我的生詞, 1 = KG 字庫
    @State private var isForceRefreshing = false
    @State private var selectedEntry: VocabularyEntry?
    @State private var activeReviewSession: TodayReviewSession?

    var body: some View {
        NavigationStack {
            VocabularyListPresenter(
                state: presenterState,
                selectedTab: $selectedTab,
                searchText: $searchText
            ) {
                routedContent
            }
            .navigationTitle("生詞庫")
            .navigationBarTitleDisplayMode(.large)
            .toolbarBackground(.hidden, for: .navigationBar)
            .toolbar {
                // Sync button
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        showSyncView = true
                    } label: {
                        VocabToolbarGlyph(
                            systemImage: "arrow.triangle.2.circlepath",
                            badge: pendingCount > 0 ? "\(pendingCount)" : nil
                        )
                    }
                }

                // Force refresh (知識庫 tab only)
                if selectedTab == 1 && authManager.isLoggedIn {
                    if knowledgeReviewCount > 0 {
                        ToolbarItem(placement: .topBarTrailing) {
                            Button {
                                startKnowledgeReview()
                            } label: {
                                VocabToolbarGlyph(
                                    systemImage: "rectangle.stack.badge.play",
                                    badge: "\(knowledgeReviewCount)"
                                )
                            }
                        }
                    }

                    ToolbarItem(placement: .topBarTrailing) {
                        Button {
                            Task { await forceRefresh() }
                        } label: {
                            if isForceRefreshing {
                                ProgressView().scaleEffect(0.8)
                            } else {
                                VocabToolbarGlyph(systemImage: "arrow.clockwise")
                            }
                        }
                        .disabled(isForceRefreshing)
                    }
                }

                // Export menu (only for local vocab tab)
                if selectedTab == 0 && !pendingEntries.isEmpty {
                    ToolbarItem(placement: .topBarTrailing) {
                        Menu {
                            Button {
                                exportCSV()
                            } label: {
                                Label("匯出 CSV", systemImage: "tablecells")
                            }

                            Button {
                                exportJSON()
                            } label: {
                                Label("匯出 JSON", systemImage: "doc.text")
                            }

                            Button {
                                exportAnki()
                            } label: {
                                Label("匯出 Anki TSV", systemImage: "rectangle.stack")
                            }
                        } label: {
                            VocabToolbarGlyph(systemImage: "square.and.arrow.up")
                        }
                    }
                }
            }
            .sheet(isPresented: $showSyncView) {
                SyncView()
            }
            .sheet(isPresented: $showSettings) {
                SettingsView()
            }
            .sheet(item: $exportURL) { url in
                ShareSheet(url: url)
            }
            .sheet(item: $selectedEntry) { entry in
                WordDetailSheet(entry: entry)
                    .presentationDetents([.medium, .large])
                    .presentationDragIndicator(.visible)
                    .presentationContentInteraction(.scrolls)
            }
            .fullScreenCover(item: $activeReviewSession) { session in
                TodayReviewView(
                    entries: session.entries,
                    onClose: { activeReviewSession = nil }
                )
            }
            .task {
                await kgService.healthCheck()
            }
            .onChange(of: selectedTab) { _, _ in
                searchText = ""  // 清空搜尋
            }
        }
        .vocabSkin(.mochiNeutral)
    }

    // MARK: - Local Vocab Content

    private var presenterState: VocabularyListPresenterState {
        .init(
            tabOptions: tabOptions,
            showsSearchField: showsSearchField,
            searchPrompt: selectedTab == 0 ? "搜尋待收錄單字" : "搜尋知識庫"
        )
    }

    @ViewBuilder
    private var routedContent: some View {
        if selectedTab == 0 {
            localVocabContent
        } else if !authManager.isLoggedIn {
            loggedOutState
        } else if selectedTab == 1 {
            KGVocabView(searchText: $searchText)
        } else {
            KnowledgeGraphView()
        }
    }

    @ViewBuilder
    private var localVocabContent: some View {
        if filteredEntries.isEmpty {
            ScrollView {
                VocabEmptyStateCard(
                    title: "沒有待收錄的生詞",
                    systemImage: "character.book.closed",
                    description: "閱讀時點擊的單字會出現在這裡，同步後移入知識庫。"
                )
                .padding(.horizontal)
                .padding(.top, 16)
            }
        } else {
            ScrollView {
                VStack(spacing: 16) {
                    VocabCard {
                        HStack(alignment: .firstTextBaseline) {
                            VStack(alignment: .leading, spacing: 4) {
                                Text("待收錄")
                                    .font(vocabSkin.typography.sectionTitle)
                                    .foregroundStyle(vocabSkin.palette.primaryText)
                                Text("同步前的本地收件匣，會保留新增與待刪除動作。")
                                    .font(vocabSkin.typography.body)
                                    .foregroundStyle(vocabSkin.palette.secondaryText)
                            }

                            Spacer()

                            Text("\(filteredEntries.count)")
                                .font(vocabSkin.typography.numericHero)
                                .foregroundStyle(vocabSkin.palette.quaternaryText)
                        }
                    }

                    VocabCard(padding: 0) {
                        LazyVStack(spacing: 0) {
                            ForEach(Array(filteredEntries.enumerated()), id: \.element.id) { index, entry in
                                HStack(alignment: .top, spacing: 12) {
                                    WordRow(viewData: entry.wordRowViewData())
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .contentShape(Rectangle())
                                    .onTapGesture { selectedEntry = entry }

                                    Button {
                                        handlePendingRemoval(entry)
                                    } label: {
                                        Image(systemName: entry.actionType == "delete" ? "arrow.uturn.backward.circle" : "trash")
                                            .font(.system(size: 15, weight: .medium))
                                            .foregroundStyle(entry.actionType == "delete" ? vocabSkin.palette.secondaryText : vocabSkin.palette.tertiaryText)
                                            .frame(width: 30, height: 30)
                                            .background(
                                                RoundedRectangle(cornerRadius: vocabSkin.radii.tiny, style: .continuous)
                                                    .fill(vocabSkin.palette.mutedFill)
                                            )
                                    }
                                    .buttonStyle(.plain)
                                    .padding(.top, 10)
                                }
                                .padding(.horizontal, 18)

                                if index < filteredEntries.count - 1 {
                                    Divider()
                                        .padding(.leading, 18)
                                }
                            }
                        }
                    }
                }
                .padding(.horizontal)
                .padding(.top, 10)
                .padding(.bottom, 24)
            }
        }
    }

    // MARK: - Computed

    /// Entries not yet synced to KG (待收錄)
    private var pendingEntries: [VocabularyEntry] {
        allEntries.filter { $0.syncStatus != 1 }
    }

    private var pendingCount: Int {
        pendingEntries.count
    }

    private var showsSearchField: Bool {
        selectedTab == 0 || (selectedTab == 1 && authManager.isLoggedIn)
    }

    private var syncedKnowledgeEntries: [VocabularyEntry] {
        allEntries
            .filter { $0.syncStatus == 1 && $0.actionType != "delete" }
            .sorted(by: knowledgeEntrySort)
    }

    private var knowledgeReviewEntries: [VocabularyEntry] {
        syncedKnowledgeEntries.filter { $0.reviewState == .due || $0.reviewState == .unlearned }
    }

    private var knowledgeReviewCount: Int {
        knowledgeReviewEntries.count
    }

    private var tabOptions: [VocabTabOption<Int>] {
        [
            .init(id: 0, title: "待收錄", count: pendingCount, systemImage: "tray"),
            .init(
                id: 1,
                title: "知識庫",
                count: authManager.isLoggedIn ? kgService.serverCardCount : 0,
                systemImage: "books.vertical"
            ),
            .init(id: 2, title: "關聯圖", systemImage: "point.3.connected.trianglepath.dotted")
        ]
    }

    private var filteredEntries: [VocabularyEntry] {
        let sortedPending = pendingEntries.sorted {
            if $0.isReviewDue != $1.isReviewDue {
                return $0.isReviewDue && !$1.isReviewDue
            }
            if $0.nextReviewAt != $1.nextReviewAt {
                return $0.nextReviewAt < $1.nextReviewAt
            }
            return $0.dateAdded > $1.dateAdded
        }

        if searchText.isEmpty { return sortedPending }
        return sortedPending.filter {
            $0.word.localizedCaseInsensitiveContains(searchText) ||
            $0.translation.localizedCaseInsensitiveContains(searchText)
        }
    }

    // MARK: - 強制刷新

    private func forceRefresh() async {
        guard !isForceRefreshing else { return }
        isForceRefreshing = true
        await kgService.clearLocalData(container: modelContext.container, reason: "force_refresh")
        try? await kgService.pullCardsToLocal(container: modelContext.container, progress: nil)
        await kgService.healthCheck()
        isForceRefreshing = false
    }

    // MARK: - 刪除

    private func handlePendingRemoval(_ entry: VocabularyEntry) {
        if entry.actionType == "delete" {
            entry.syncStatus = 1
            entry.actionType = "add"
        } else {
            modelContext.delete(entry)
        }
        try? modelContext.save()
    }

    // MARK: - 匯出功能（委派給 VocabularyExporter）

    private func exportCSV()  { exportURL = VocabularyExporter.exportAsCSV(entries: pendingEntries) }
    private func exportJSON() { exportURL = VocabularyExporter.exportAsJSON(entries: pendingEntries) }
    private func exportAnki() { exportURL = VocabularyExporter.exportAsAnki(entries: pendingEntries) }

    private func startKnowledgeReview() {
        guard !knowledgeReviewEntries.isEmpty else { return }
        activeReviewSession = TodayReviewSession(entries: knowledgeReviewEntries)
    }

    private func knowledgeEntrySort(_ lhs: VocabularyEntry, _ rhs: VocabularyEntry) -> Bool {
        if reviewOrder(lhs.reviewState) != reviewOrder(rhs.reviewState) {
            return reviewOrder(lhs.reviewState) < reviewOrder(rhs.reviewState)
        }
        if lhs.reviewState != .reviewed && lhs.nextReviewAt != rhs.nextReviewAt {
            return lhs.nextReviewAt < rhs.nextReviewAt
        }
        let lhsTier = tierOrder(lhs.difficultyTier)
        let rhsTier = tierOrder(rhs.difficultyTier)
        if lhsTier != rhsTier {
            return lhsTier < rhsTier
        }
        return lhs.word.localizedCaseInsensitiveCompare(rhs.word) == .orderedAscending
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

    @ViewBuilder
    private var loggedOutState: some View {
        ScrollView {
            VocabCard {
                VStack(spacing: 16) {
                    VocabEmptyStateContent(
                        title: "需登入帳號",
                        systemImage: "person.crop.circle.badge.exclamationmark",
                        description: "知識庫與關聯圖功能需要登入帳號後才能存取您的雲端資料。"
                    )

                    Button("前往設定登入") {
                        showSettings = true
                    }
                    .buttonStyle(.vocabAction(.primary))
                    .frame(maxWidth: .infinity)
                }
                .padding(.vertical, 12)
            }
            .padding(.horizontal)
            .padding(.top, 16)
        }
    }
}

// MARK: - 分享表

struct ShareSheet: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: [url], applicationActivities: nil)
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}

// MARK: - URL Identifiable

extension URL: @retroactive Identifiable {
    public var id: String { absoluteString }
}
