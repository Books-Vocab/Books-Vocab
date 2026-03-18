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
    @Environment(\.kgService) var kgService
    @Environment(\.authManager) var authManager
    @Environment(\.subscriptionManager) var subscriptionManager
    @Environment(\.horizontalSizeClass) var sizeClass
    @Environment(\.appTheme) var appTheme
    @State var selectedTab = 0  // 0 = 我的生詞, 1 = KG 字庫
    @State var coordinator = VocabularyListCoordinator()

    var notebookName: String {
        notebooks.first(where: { $0.remoteId == notebookId })?.name ?? "生詞庫".localized
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
        VocabularyListPresenter(
            state: presenterState,
            selectedTab: $selectedTab,
            searchText: $searchText
        ) {
            routedContent
        }
        .navigationTitle(notebookName)
        .navigationBarTitleDisplayMode(.large)
        .modifier(VocabularyListToolbar(
            selectedTab: selectedTab,
            isLoggedIn: authManager.isLoggedIn,
            pendingCount: pendingCount,
            knowledgeReviewCount: knowledgeReviewCount,
            knowledgeDueCount: knowledgeDueCount,
            onSync: coordinator.presentSyncView,
            onStartDueReview: { coordinator.startKnowledgeReview(entries: knowledgeDueEntries) },
            onStartUnlearnedReview: { coordinator.startKnowledgeReview(entries: knowledgeUnlearnedEntries) },
            onStartAllReview: { coordinator.startKnowledgeReview(entries: knowledgeReviewEntries) },
            onExportCSV: { coordinator.exportCSV(entries: pendingEntries) },
            onExportJSON: { coordinator.exportJSON(entries: pendingEntries) },
            onExportAnki: { coordinator.exportAnki(entries: pendingEntries) },
            hasPendingEntries: !pendingEntries.isEmpty,
            knowledgeDueEntriesCount: knowledgeDueEntries.count,
            knowledgeUnlearnedEntriesCount: knowledgeUnlearnedEntries.count
        ))
        .modifier(VocabularyListSheets(
            coordinator: coordinator,
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

#Preview {
    VocabularyListView(notebookId: "default")
        .modelContainer(for: [VocabularyEntry.self], inMemory: true)
}
