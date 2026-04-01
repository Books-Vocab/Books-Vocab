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
    @Environment(\.horizontalSizeClass) var sizeClass
    @Environment(\.appTheme) var appTheme
    @Environment(\.toastCoordinator) var toastCoordinator
    @Environment(\.syncCoordinator) var syncCoordinator
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
            allEntries: allEntries,
            sizeClass: sizeClass
        ))
        #if os(macOS)
        .inspector(isPresented: Binding(
            get: { coordinator.selectedEntry != nil || coordinator.activeReviewSession != nil },
            set: { isPresented in
                if !isPresented {
                    coordinator.activeReviewSession = nil
                    coordinator.selectedEntry = nil
                }
            }
        )) {
            macInspectorContent
                .inspectorColumnWidth(min: 350, ideal: 420, max: 600)
        }
        #endif
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
    }

    #if os(macOS)
    @ViewBuilder
    private var macInspectorContent: some View {
        if let session = coordinator.activeReviewSession {
            TodayReviewView(
                entries: session.entries,
                allEntries: allEntries,
                currentUserID: AuthManager.shared.userId,
                onClose: { coordinator.activeReviewSession = nil }
            )
        } else if let entry = coordinator.selectedEntry {
            WordDetailSheet(
                entry: entry,
                allEntries: allEntries,
                wrapInNavigation: false
            )
        }
    }
    #endif
}

#Preview {
    VocabularyListView(notebookId: "default")
        .modelContainer(for: [VocabularyEntry.self], inMemory: true)
}
