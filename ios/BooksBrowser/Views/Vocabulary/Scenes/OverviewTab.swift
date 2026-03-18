//
//  OverviewTab.swift
//  BooksBrowser
//
//  頂層總覽 tab — 篩選器 + 統計儀表板。

import SwiftUI
import SwiftData

struct OverviewTab: View {
    @Environment(\.authManager) private var authManager
    @Environment(\.appTheme) private var appTheme
    @Environment(\.modelContext) private var modelContext
    @Environment(\.vocabSkin) private var skin

    @State private var filter = NotebookFilter.load()

    var body: some View {
        NavigationStack {
            if authManager.isLoggedIn || authManager.isDemoMode {
                StatsPresenter(filter: filter)
                    .toolbar {
                        ToolbarItem(placement: .topBarTrailing) {
                            NotebookFilterChip(filter: $filter)
                        }
                    }
                    .navigationTitle("總覽".localized)
                    .navigationBarTitleDisplayMode(.large)
            } else {
                loggedOutState
            }
        }
    }

    @ViewBuilder
    private var loggedOutState: some View {
        ScrollView {
            VStack(spacing: AppShellMetrics.sectionSpacing) {
                AppEmptyStateCard(
                    title: "需登入帳號".localized,
                    systemImage: "person.crop.circle.badge.exclamationmark",
                    description: "總覽功能需要登入帳號後才能存取您的雲端資料。".localized
                )
            }
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
            .padding(.top, AppMetrics.spacingMedium)
        }
        .navigationTitle("總覽".localized)
        .navigationBarTitleDisplayMode(.large)
    }
}

#Preview {
    OverviewTab()
        .modelContainer(for: [VocabularyEntry.self, ReviewRecord.self, Notebook.self], inMemory: true)
}
