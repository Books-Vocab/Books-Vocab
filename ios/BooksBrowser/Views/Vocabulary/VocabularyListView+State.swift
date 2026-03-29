//
//  VocabularyListView+State.swift
//  BooksBrowser
//

import SwiftUI

extension VocabularyListView {

    func presenterState(classified: VocabularyEntryPresentation.ClassifiedResult) -> VocabularyListPresenterState {
        .init(
            tabOptions: tabOptions(classified: classified),
            showsSearchField: showsSearchField,
            searchPrompt: selectedTab == 0 ? "搜尋待收錄單字".localized : "搜尋單字".localized
        )
    }

    func pendingPresenterState(classified: VocabularyEntryPresentation.ClassifiedResult) -> PendingVocabPresenterState {
        let syncedCount = classified.dueCount + classified.unlearnedCount + classified.reviewedCount
        return PendingVocabPresenterState(
            pendingCount: filteredPendingEntries.count,
            rows: filteredPendingEntries.map { entry in
                .init(
                    id: entry.id,
                    row: entry.wordRowViewData(),
                    actionSystemImage: entry.syncAction == .delete ? "arrow.uturn.backward.circle" : "trash",
                    actionTone: entry.syncAction == .delete ? .secondary : .tertiary
                )
            },
            knowledgeCount: syncedCount,
            dueCount: classified.dueCount
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

    func tabOptions(classified: VocabularyEntryPresentation.ClassifiedResult) -> [VocabTabOption<Int>] {
        let syncedCount = classified.dueCount + classified.unlearnedCount + classified.reviewedCount
        return [
            .init(id: 0, title: "待收錄".localized, count: pendingCount, systemImage: "tray"),
            .init(
                id: 1,
                title: "已收錄".localized,
                count: syncedCount,
                systemImage: "books.vertical"
            ),
        ]
    }


    var filteredPendingEntries: [VocabularyEntry] {
        VocabularyEntryPresentation.filteredPendingEntries(
            in: allEntries,
            searchText: debouncedSearchText
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
    func routedContent(classified: VocabularyEntryPresentation.ClassifiedResult) -> some View {
        Group {
            if selectedTab == 0 {
                PendingVocabPresenter(
                    state: pendingPresenterState(classified: classified),
                    onRowTapped: handlePendingRowTap,
                    onActionTapped: handlePendingActionTap,
                    onSwitchToKnowledge: switchToKnowledgeTab
                )
            } else if !authManager.isLoggedIn {
                loggedOutState
            } else {
                KGVocabView(searchText: $debouncedSearchText, notebookId: notebookId)
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
                    description: "此功能需要登入帳號後才能存取您的雲端資料。".localized
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
