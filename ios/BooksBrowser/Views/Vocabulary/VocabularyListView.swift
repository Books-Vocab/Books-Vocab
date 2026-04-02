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
    @Query var allEntries: [VocabularyEntry]
    @Query private var notebooks: [Notebook]
    @Environment(\.modelContext) var modelContext

    let notebookId: String

    @State var searchText = ""
    /// debounce 後的搜尋文字，用於實際過濾
    @State var debouncedSearchText = ""
    @Environment(\.kgService) var kgService
    @Environment(\.authManager) var authManager
    @Environment(\.subscriptionManager) var subscriptionManager
    @Environment(\.appTheme) var appTheme
    @Environment(\.toastCoordinator) var toastCoordinator
    @Environment(\.syncCoordinator) var syncCoordinator
    @Environment(\.detailRouter) var detailRouter
    @State var selectedTab = 0  // 0 = 我的生詞, 1 = KG 字庫
    @State var coordinator = VocabularyListCoordinator()

    var notebookName: String {
        notebooks.first(where: { $0.remoteId == notebookId })?.name ?? "單字本".localized
    }

    init(notebookId: String = "default") {
        self.notebookId = notebookId
        let nbId = notebookId
        _allEntries = Query(
            filter: #Predicate<VocabularyEntry> { $0.notebookId == nbId },
            sort: \.dateAdded,
            order: .reverse
        )
        _notebooks = Query(sort: \Notebook.sortOrder)
    }

    var body: some View {
        let classified = VocabularyEntryPresentation.classifyKnowledgeEntries(in: allEntries, now: Date())

        VocabularyListPresenter(
            state: presenterState(classified: classified),
            selectedTab: $selectedTab,
            searchText: $searchText
        ) {
            routedContent(classified: classified)
        }
        .navigationTitle(notebookName)
        .largeNavigationBarTitle()
        .modifier(VocabularyListToolbar(
            selectedTab: selectedTab,
            isLoggedIn: authManager.isLoggedIn,
            isSyncing: syncCoordinator.phase == .running,
            pendingCount: pendingCount,
            knowledgeReviewCount: classified.dueCount + classified.unlearnedCount,
            knowledgeDueCount: classified.dueCount,
            onSync: coordinator.presentSyncView,
            onStartDueReview: { coordinator.startKnowledgeReview(entries: classified.dueBucket) },
            onStartUnlearnedReview: { coordinator.startKnowledgeReview(entries: classified.unlearnedBucket) },
            onStartAllReview: { coordinator.startKnowledgeReview(entries: classified.dueBucket + classified.unlearnedBucket) },
            onExportCSV: { coordinator.exportCSV(entries: pendingEntries, toastCoordinator: toastCoordinator) },
            onExportJSON: { coordinator.exportJSON(entries: pendingEntries, toastCoordinator: toastCoordinator) },
            onExportAnki: { coordinator.exportAnki(entries: pendingEntries, toastCoordinator: toastCoordinator) },
            hasPendingEntries: !pendingEntries.isEmpty,
            knowledgeDueEntriesCount: classified.dueCount,
            knowledgeUnlearnedEntriesCount: classified.unlearnedCount
        ))
        .modifier(VocabularyListSheets(
            coordinator: coordinator,
            allEntries: allEntries
        ))
        .task {
            guard !authManager.isDemoMode else { return }
            await kgService.healthCheck()
        }
        .onChange(of: selectedTab) { _, _ in
            searchText = ""
            debouncedSearchText = ""
        }
        .task(id: searchText) {
            // 清空時立即反映；否則 debounce 300ms
            guard !searchText.isEmpty else {
                debouncedSearchText = ""
                return
            }
            do {
                try await Task.sleep(for: .milliseconds(300))
                debouncedSearchText = searchText
            } catch {
                // Task cancelled — 使用者繼續輸入，忽略
            }
        }
        .onChange(of: coordinator.selectedEntry) { _, entry in
            if let entry, let detailRouter {
                detailRouter.showWordDetail(entry, allEntries: allEntries)
                coordinator.selectedEntry = nil
            }
        }
        .onChange(of: coordinator.activeReviewSession) { _, session in
            if let session, let detailRouter {
                detailRouter.showReview(session, allEntries: allEntries)
                coordinator.activeReviewSession = nil
            }
        }
    }

}

#Preview {
    VocabularyListView(notebookId: "default")
        .modelContainer(for: [VocabularyEntry.self], inMemory: true)
}
