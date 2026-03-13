//
//  VocabularyListView+State.swift
//  BooksBrowser
//

import SwiftUI

extension VocabularyListView {

    var presenterState: VocabularyListPresenterState {
        .init(
            tabOptions: tabOptions,
            showsSearchField: showsSearchField,
            searchPrompt: selectedTab == 0 ? "搜尋待收錄單字".localized : "搜尋知識庫".localized
        )
    }

    var pendingPresenterState: PendingVocabPresenterState {
        PendingVocabPresenterState(
            pendingCount: filteredPendingEntries.count,
            rows: filteredPendingEntries.map { entry in
                .init(
                    id: entry.id,
                    row: entry.wordRowViewData(),
                    actionSystemImage: entry.syncAction == .delete ? "arrow.uturn.backward.circle" : "trash",
                    actionTone: entry.syncAction == .delete ? .secondary : .tertiary
                )
            },
            knowledgeCount: authManager.isDemoMode
                ? syncedKnowledgeEntries.count
                : (authManager.isLoggedIn ? kgService.serverCardCount : 0),
            dueCount: knowledgeDueCount
        )
    }

    var pendingEntries: [VocabularyEntry] {
        VocabularyEntryPresentation.pendingEntries(in: allEntries)
    }

    var pendingCount: Int {
        pendingEntries.count
    }

    var showsSearchField: Bool {
        selectedTab == 0 || (selectedTab == 1 && authManager.isLoggedIn)
    }

    var syncedKnowledgeEntries: [VocabularyEntry] {
        VocabularyEntryPresentation.syncedKnowledgeEntries(in: allEntries)
    }

    var knowledgeReviewEntries: [VocabularyEntry] {
        VocabularyEntryPresentation.knowledgeReviewEntries(in: allEntries)
    }

    var knowledgeReviewCount: Int {
        knowledgeReviewEntries.count
    }

    var knowledgeDueEntries: [VocabularyEntry] {
        VocabularyEntryPresentation.knowledgeDueEntries(in: allEntries)
    }

    var knowledgeDueCount: Int {
        knowledgeDueEntries.count
    }

    var knowledgeUnlearnedEntries: [VocabularyEntry] {
        VocabularyEntryPresentation.knowledgeUnlearnedEntries(in: allEntries)
    }

    var tabOptions: [VocabTabOption<Int>] {
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
            .init(id: 2, title: "總覽".localized, systemImage: "chart.bar")
        ]
    }

    var archivedCount: Int {
        VocabularyEntryPresentation.archivedEntries(in: allEntries).count
    }

    var filteredPendingEntries: [VocabularyEntry] {
        VocabularyEntryPresentation.filteredPendingEntries(
            in: allEntries,
            searchText: searchText
        )
    }

    func switchToKnowledgeTab() {
        selectedTab = 1
    }

    func handlePendingRowTap(_ entryID: UUID) {
        coordinator.handlePendingRowTap(entryID, pendingEntries: pendingEntries)
    }

    func handlePendingActionTap(_ entryID: UUID) {
        coordinator.handlePendingActionTap(
            entryID,
            pendingEntries: pendingEntries,
            modelContext: modelContext
        )
    }

    // MARK: - Routed Content

    @ViewBuilder
    var routedContent: some View {
        Group {
            if selectedTab == 0 {
                PendingVocabPresenter(
                    state: pendingPresenterState,
                    onRowTapped: handlePendingRowTap,
                    onActionTapped: handlePendingActionTap,
                    onSwitchToKnowledge: switchToKnowledgeTab
                )
            } else if !authManager.isLoggedIn {
                loggedOutState
            } else if selectedTab == 1 {
                KGVocabView(searchText: $searchText)
            } else {
                StatsPresenter(allEntries: allEntries)
            }
        }
        .transition(.contentSwap)
    }

    // MARK: - Logged Out

    @ViewBuilder
    var loggedOutState: some View {
        ScrollView {
            VStack(spacing: AppShellMetrics.sectionSpacing) {
                AppEmptyStateCard(
                    title: "需登入帳號".localized,
                    systemImage: "person.crop.circle.badge.exclamationmark",
                    description: "知識庫與總覽功能需要登入帳號後才能存取您的雲端資料。".localized
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
                    .foregroundStyle(appTheme.palette.accent)
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
            .padding(.top, AppMetrics.spacingMedium)
        }
    }
}
