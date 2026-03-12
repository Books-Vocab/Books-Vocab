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

    @State private var searchText = ""
    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager
    @Environment(\.subscriptionManager) private var subscriptionManager
    @Environment(\.horizontalSizeClass) private var sizeClass
    @State private var selectedTab = 0  // 0 = 我的生詞, 1 = KG 字庫
    @State private var showArchiveList = false
    @State private var coordinator = VocabularyListCoordinator()

    var body: some View {
        NavigationStack {
            VocabularyListPresenter(
                state: presenterState,
                selectedTab: $selectedTab,
                searchText: $searchText
            ) {
                routedContent
            }
            .navigationTitle("生詞庫".localized)
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                // Sync button
                ToolbarItem(placement: .topBarLeading) {
                    Button(action: coordinator.presentSyncView) {
                        VocabToolbarGlyph(
                            systemImage: "arrow.triangle.2.circlepath",
                            badge: pendingCount > 0 ? "\(pendingCount)" : nil
                        )
                    }
                    .accessibilityLabel("同步詞彙".localized)
                }

                // Force refresh (知識庫 tab only)
                if selectedTab == 1 && authManager.isLoggedIn {
                    if knowledgeReviewCount > 0 {
                        ToolbarItem(placement: .topBarTrailing) {
                            Menu {
                                if !knowledgeDueEntries.isEmpty {
                                    Button {
                                        coordinator.startKnowledgeReview(entries: knowledgeDueEntries)
                                    } label: {
                                        Label(
                                            L10n.format("複習到期卡片（%@）", "\(knowledgeDueEntries.count)"),
                                            systemImage: "clock.badge.exclamationmark"
                                        )
                                    }
                                }

                                if !knowledgeUnlearnedEntries.isEmpty {
                                    Button {
                                        coordinator.startKnowledgeReview(entries: knowledgeUnlearnedEntries)
                                    } label: {
                                        Label(
                                            L10n.format("學習新卡片（%@）", "\(knowledgeUnlearnedEntries.count)"),
                                            systemImage: "sparkles"
                                        )
                                    }
                                }

                                Divider()

                                Button {
                                    coordinator.startKnowledgeReview(entries: knowledgeReviewEntries)
                                } label: {
                                    Label(
                                        L10n.format("全部複習（%@）", "\(knowledgeReviewCount)"),
                                        systemImage: "rectangle.stack"
                                    )
                                }
                            } label: {
                                VocabToolbarGlyph(
                                    systemImage: "rectangle.stack.badge.play",
                                    badge: knowledgeDueCount > 0 ? "\(knowledgeDueCount)" : "\(knowledgeReviewCount)"
                                )
                            }
                        }
                    }

                    ToolbarItem(placement: .topBarTrailing) {
                        Button { showArchiveList = true } label: {
                            VocabToolbarGlyph(
                                systemImage: "archivebox",
                                badge: archivedCount > 0 ? "\(archivedCount)" : nil
                            )
                        }
                    }
                }

                // Export menu (only for local vocab tab)
                if selectedTab == 0 && !pendingEntries.isEmpty {
                    ToolbarItem(placement: .topBarTrailing) {
                        Menu {
                            Button {
                                coordinator.exportCSV(entries: pendingEntries)
                            } label: {
                                Label("匯出 CSV".localized, systemImage: "tablecells")
                            }

                            Button {
                                coordinator.exportJSON(entries: pendingEntries)
                            } label: {
                                Label("匯出 JSON".localized, systemImage: "doc.text")
                            }

                            Button {
                                coordinator.exportAnki(entries: pendingEntries)
                            } label: {
                                Label("匯出 Anki TSV".localized, systemImage: "rectangle.stack")
                            }
                        } label: {
                            VocabToolbarGlyph(systemImage: "square.and.arrow.up")
                        }
                    }
                }
            }
            .sheet(isPresented: $coordinator.showSyncView) {
                SyncView()
            }
            .sheet(isPresented: $coordinator.showSettings) {
                SettingsView()
            }
            .sheet(isPresented: $showArchiveList) {
                ArchivedVocabSheet()
            }
            .sheet(item: $coordinator.exportURL) { url in
                ShareSheet(url: url)
            }
            .sheet(item: $coordinator.selectedEntry) { entry in
                WordDetailSheet(entry: entry)
                    .presentationDetents([.large])
                    .presentationDragIndicator(.visible)
                    .presentationContentInteraction(.scrolls)
            }
            .fullScreenCover(item: Binding(
                get: { sizeClass == .compact ? coordinator.activeReviewSession : nil },
                set: { coordinator.activeReviewSession = $0 }
            )) { session in
                TodayReviewView(
                    entries: session.entries,
                    onClose: { coordinator.activeReviewSession = nil }
                )
            }
            .sheet(item: Binding(
                get: { sizeClass == .regular ? coordinator.activeReviewSession : nil },
                set: { coordinator.activeReviewSession = $0 }
            )) { session in
                TodayReviewView(
                    entries: session.entries,
                    onClose: { coordinator.activeReviewSession = nil }
                )
                .presentationDetents([.large])
            }
            .task {
                guard !authManager.isDemoMode else { return }
                await kgService.healthCheck()
            }
            .onChange(of: selectedTab) { _, _ in
                searchText = ""  // 清空搜尋
            }
        }
    }

    // MARK: - Local Vocab Content

    private var presenterState: VocabularyListPresenterState {
        .init(
            tabOptions: tabOptions,
            showsSearchField: showsSearchField,
            searchPrompt: selectedTab == 0 ? "搜尋待收錄單字".localized : "搜尋知識庫".localized
        )
    }

    @ViewBuilder
    private var routedContent: some View {
        if selectedTab == 0 {
            PendingVocabPresenter(
                state: pendingPresenterState,
                onRowTapped: handlePendingRowTap,
                onActionTapped: handlePendingActionTap
            )
        } else if !authManager.isLoggedIn {
            loggedOutState
        } else if selectedTab == 1 {
            KGVocabView(searchText: $searchText)
        } else if selectedTab == 2 {
            KnowledgeGraphView()
        } else {
            StatsPresenter()
        }
    }

    // MARK: - Computed

    private var pendingPresenterState: PendingVocabPresenterState {
        PendingVocabPresenterState(
            pendingCount: filteredPendingEntries.count,
            rows: filteredPendingEntries.map { entry in
                .init(
                    id: entry.id,
                    row: entry.wordRowViewData(),
                    actionSystemImage: entry.syncAction == .delete ? "arrow.uturn.backward.circle" : "trash",
                    actionTone: entry.syncAction == .delete ? .secondary : .tertiary
                )
            }
        )
    }

    /// Entries not yet synced to KG (待收錄)
    private var pendingEntries: [VocabularyEntry] {
        VocabularyEntryPresentation.pendingEntries(in: allEntries)
    }

    private var pendingCount: Int {
        pendingEntries.count
    }

    private var showsSearchField: Bool {
        selectedTab == 0 || (selectedTab == 1 && authManager.isLoggedIn)
        // Tab 2 (關聯圖) and 3 (統計) don't need search
    }

    private var syncedKnowledgeEntries: [VocabularyEntry] {
        VocabularyEntryPresentation.syncedKnowledgeEntries(in: allEntries)
    }

    private var knowledgeReviewEntries: [VocabularyEntry] {
        VocabularyEntryPresentation.knowledgeReviewEntries(in: allEntries)
    }

    private var knowledgeReviewCount: Int {
        knowledgeReviewEntries.count
    }

    private var knowledgeDueEntries: [VocabularyEntry] {
        VocabularyEntryPresentation.knowledgeDueEntries(in: allEntries)
    }

    private var knowledgeDueCount: Int {
        knowledgeDueEntries.count
    }

    private var knowledgeUnlearnedEntries: [VocabularyEntry] {
        VocabularyEntryPresentation.knowledgeUnlearnedEntries(in: allEntries)
    }

    private var tabOptions: [VocabTabOption<Int>] {
        [
            .init(id: 0, title: "待收錄".localized, count: pendingCount, systemImage: "tray"),
            .init(
                id: 1,
                title: "知識庫".localized,
                count: authManager.isDemoMode
                    ? syncedKnowledgeEntries.count
                    : (authManager.isLoggedIn ? kgService.serverCardCount : 0),
                systemImage: "books.vertical"
            ),
            .init(id: 2, title: "關聯圖".localized, systemImage: "point.3.connected.trianglepath.dotted"),
            .init(id: 3, title: "統計".localized, systemImage: "chart.bar")
        ]
    }

    private var archivedCount: Int {
        VocabularyEntryPresentation.archivedEntries(in: allEntries).count
    }

    private var filteredPendingEntries: [VocabularyEntry] {
        VocabularyEntryPresentation.filteredPendingEntries(
            in: allEntries,
            searchText: searchText
        )
    }

    private func handlePendingRowTap(_ entryID: UUID) {
        coordinator.handlePendingRowTap(entryID, pendingEntries: pendingEntries)
    }

    private func handlePendingActionTap(_ entryID: UUID) {
        coordinator.handlePendingActionTap(
            entryID,
            pendingEntries: pendingEntries,
            modelContext: modelContext
        )
    }

    @ViewBuilder
    private var loggedOutState: some View {
        ScrollView {
            VStack(spacing: AppShellMetrics.sectionSpacing) {
                AppEmptyStateCard(
                    title: "需登入帳號".localized,
                    systemImage: "person.crop.circle.badge.exclamationmark",
                    description: "知識庫與關聯圖功能需要登入帳號後才能存取您的雲端資料。".localized
                )

                Button("前往設定登入".localized) {
                    coordinator.presentSettings()
                }
                .buttonStyle(.appAction(.primary))

                Button(action: {
                    authManager.enterDemoMode(modelContainer: modelContext.container)
                }) {
                    HStack(spacing: 6) {
                        Image(systemName: "play.circle")
                        Text("先體驗看看".localized)
                    }
                    .font(AppFonts.body(weight: .medium))
                    .foregroundStyle(AppColors.tint)
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
            .padding(.top, AppMetrics.spacingMedium)
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
