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
    @Query(sort: \VocabularyEntry.dateAdded, order: .reverse) var allEntries: [VocabularyEntry]
    @Environment(\.modelContext) var modelContext

    @State var searchText = ""
    @Environment(\.kgService) var kgService
    @Environment(\.authManager) var authManager
    @Environment(\.subscriptionManager) var subscriptionManager
    @Environment(\.horizontalSizeClass) var sizeClass
    @Environment(\.appTheme) var appTheme
    @State var selectedTab = 0  // 0 = 我的生詞, 1 = KG 字庫
    @State var showArchiveList = false
    @State var coordinator = VocabularyListCoordinator()

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
            .modifier(VocabularyListToolbar(
                selectedTab: selectedTab,
                isLoggedIn: authManager.isLoggedIn,
                pendingCount: pendingCount,
                knowledgeReviewCount: knowledgeReviewCount,
                knowledgeDueCount: knowledgeDueCount,
                archivedCount: archivedCount,
                onSync: coordinator.presentSyncView,
                onStartDueReview: { coordinator.startKnowledgeReview(entries: knowledgeDueEntries) },
                onStartUnlearnedReview: { coordinator.startKnowledgeReview(entries: knowledgeUnlearnedEntries) },
                onStartAllReview: { coordinator.startKnowledgeReview(entries: knowledgeReviewEntries) },
                onShowArchive: { showArchiveList = true },
                onExportCSV: { coordinator.exportCSV(entries: pendingEntries) },
                onExportJSON: { coordinator.exportJSON(entries: pendingEntries) },
                onExportAnki: { coordinator.exportAnki(entries: pendingEntries) },
                hasPendingEntries: !pendingEntries.isEmpty,
                knowledgeDueEntriesCount: knowledgeDueEntries.count,
                knowledgeUnlearnedEntriesCount: knowledgeUnlearnedEntries.count
            ))
            .modifier(VocabularyListSheets(
                coordinator: coordinator,
                showArchiveList: $showArchiveList,
                allEntries: allEntries,
                sizeClass: sizeClass
            ))
            .task {
                guard !authManager.isDemoMode else { return }
                await kgService.healthCheck()
            }
            .onChange(of: selectedTab) { _, _ in
                searchText = ""
            }
        }
    }
}

#Preview {
    VocabularyListView()
        .modelContainer(for: [VocabularyEntry.self], inMemory: true)
}
