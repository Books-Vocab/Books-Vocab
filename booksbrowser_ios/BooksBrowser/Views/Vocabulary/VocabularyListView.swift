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
    @State private var selectedTab = 0  // 0 = 我的生詞, 1 = KG 字庫
    @StateObject private var coordinator = VocabularyListCoordinator()

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
                    Button(action: coordinator.presentSyncView) {
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
                                coordinator.startKnowledgeReview(entries: knowledgeReviewEntries)
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
                            Task {
                                await coordinator.forceRefresh(
                                    kgService: kgService,
                                    modelContext: modelContext
                                )
                            }
                        } label: {
                            if coordinator.isForceRefreshing {
                                ProgressView().scaleEffect(0.8)
                            } else {
                                VocabToolbarGlyph(systemImage: "arrow.clockwise")
                            }
                        }
                        .disabled(coordinator.isForceRefreshing)
                    }
                }

                // Export menu (only for local vocab tab)
                if selectedTab == 0 && !pendingEntries.isEmpty {
                    ToolbarItem(placement: .topBarTrailing) {
                        Menu {
                            Button {
                                coordinator.exportCSV(entries: pendingEntries)
                            } label: {
                                Label("匯出 CSV", systemImage: "tablecells")
                            }

                            Button {
                                coordinator.exportJSON(entries: pendingEntries)
                            } label: {
                                Label("匯出 JSON", systemImage: "doc.text")
                            }

                            Button {
                                coordinator.exportAnki(entries: pendingEntries)
                            } label: {
                                Label("匯出 Anki TSV", systemImage: "rectangle.stack")
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
            .sheet(item: $coordinator.exportURL) { url in
                ShareSheet(url: url)
            }
            .sheet(item: $coordinator.selectedEntry) { entry in
                WordDetailSheet(entry: entry)
                    .presentationDetents([.medium, .large])
                    .presentationDragIndicator(.visible)
                    .presentationContentInteraction(.scrolls)
            }
            .fullScreenCover(item: $coordinator.activeReviewSession) { session in
                TodayReviewView(
                    entries: session.entries,
                    onClose: { coordinator.activeReviewSession = nil }
                )
            }
            .task {
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
            searchPrompt: selectedTab == 0 ? "搜尋待收錄單字" : "搜尋知識庫"
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
        } else {
            KnowledgeGraphView()
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
                    actionSystemImage: entry.actionType == "delete" ? "arrow.uturn.backward.circle" : "trash",
                    actionTone: entry.actionType == "delete" ? .secondary : .tertiary
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
                    title: "需登入帳號",
                    systemImage: "person.crop.circle.badge.exclamationmark",
                    description: "知識庫與關聯圖功能需要登入帳號後才能存取您的雲端資料。"
                )

                Button("前往設定登入") {
                    coordinator.presentSettings()
                }
                .buttonStyle(.appAction(.primary))
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
