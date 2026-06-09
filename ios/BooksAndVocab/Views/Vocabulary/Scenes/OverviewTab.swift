//
//  OverviewTab.swift
//  Books & Vocab
//
//  頂層總覽 tab — 篩選器 + 統計儀表板。

import SwiftUI
import SwiftData

struct OverviewTab: View {
    @ObserveInjection private var inject
    @Environment(\.authManager) private var authManager
    @Environment(\.appTheme) private var appTheme
    @Environment(\.modelContext) private var modelContext
    @Environment(\.appSkin) private var skin

    @State private var filter = NotebookFilter.load()
    @State private var loginGate = LoginGateState()

    var body: some View {
        NavigationStack {
            if authManager.isLoggedIn || authManager.isDemoMode {
                StatsPresenter(filter: filter)
                    .toolbar {
                        ToolbarItem(placement: .confirmationAction) {
                            NotebookFilterChip(filter: $filter)
                        }
                    }
                    .navigationTitle("總覽".localized)
                    .largeNavigationBarTitle()
            } else {
                loggedOutState
            }
        }
        .enableInjection()
    }

    @ViewBuilder
    private var loggedOutState: some View {
        ScrollView {
            VStack(spacing: AppShellMetrics.sectionSpacing) {
                AppEmptyStateCard(
                    title: "需登入帳號".localized,
                    systemImage: "person.crop.circle.badge.exclamationmark",
                    description: "總覽功能需要登入帳號後才能存取您的雲端資料。".localized,
                    action: .init(title: "登入帳號".localized, systemImage: "person.crop.circle", handler: { loginGate.presentLogin() })
                )
            }
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
            .padding(.top, AppSpacing.s4)
        }
        .navigationTitle("總覽".localized)
        .largeNavigationBarTitle()
        .loginGateSheet($loginGate)
    }
}

#Preview {
    OverviewTab()
        .modelContainer(for: [VocabularyEntry.self, ReviewRecord.self, Notebook.self], inMemory: true)
}
