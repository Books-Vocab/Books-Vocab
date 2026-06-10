//
//  VocabularyListView.swift
//  Books & Vocab
//
//  Created by 陳亮宇 on 2026/2/24.
//

import SwiftUI
import SwiftData

private enum Metrics {
    static let searchDebounce: Duration = .milliseconds(300)
}

/// 單字本內的已收錄列表
struct VocabularyListView: View {
    @ObserveInjection private var inject
    @Query var allEntries: [VocabularyEntry]
    @Query private var notebooks: [Notebook]
    @Environment(\.modelContext) var modelContext
    @Environment(\.catalogTaskPolicy) private var catalogTaskPolicy

    let notebookId: String

    @State var searchText = ""
    @State var debouncedSearchText = ""
    @Environment(\.kgService) var kgService
    @Environment(\.authManager) var authManager
    @Environment(\.subscriptionManager) var subscriptionManager
    @Environment(\.appTheme) var appTheme
    @Environment(\.toastCoordinator) var toastCoordinator
    @Environment(\.syncCoordinator) var syncCoordinator
    @Environment(\.detailRouter) var detailRouter
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
        VocabularyListPresenter(
            showsSearchField: authManager.isLoggedIn,
            searchText: $searchText
        ) {
            contentView()
        }
        .navigationTitle(notebookName)
        .largeNavigationBarTitle()
        .modifier(VocabularyListToolbar(
            isLoggedIn: authManager.isLoggedIn,
            isSyncing: syncCoordinator.phase == .running,
            pendingCount: pendingCount,
            onSync: coordinator.presentSyncView,
            onExportCSV: { coordinator.exportCSV(entries: syncedEntries, toastCoordinator: toastCoordinator) },
            onExportJSON: { coordinator.exportJSON(entries: syncedEntries, toastCoordinator: toastCoordinator) },
            onExportAnki: { coordinator.exportAnki(entries: syncedEntries, toastCoordinator: toastCoordinator) },
            hasSyncedEntries: !syncedEntries.isEmpty
        ))
        .modifier(VocabularyListSheets(
            coordinator: coordinator,
            allEntries: allEntries
        ))
        .task {
            guard catalogTaskPolicy.runsTasks else { return }
            guard !authManager.isDemoMode else { return }
            await kgService.healthCheck()
        }
        .task(id: searchText) {
            guard !searchText.isEmpty else {
                debouncedSearchText = ""
                return
            }
            try? await Task.sleep(for: Metrics.searchDebounce)
            debouncedSearchText = searchText
            PerfLog.search.mark("search.query.committed", "query=\(searchText)")
        }
        .onChange(of: coordinator.activeReviewSession) { _, session in
            if let session, let detailRouter {
                detailRouter.showReview(session, allEntries: allEntries)
                coordinator.activeReviewSession = nil
            }
        }
        .enableInjection()
    }

}

#Preview {
    VocabularyListView(notebookId: "default")
        .modelContainer(for: [VocabularyEntry.self], inMemory: true)
}
