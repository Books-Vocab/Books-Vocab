//
//  ContentView.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/24.
//

import SwiftUI
import SwiftData

/// 主介面 — Tab 導航
struct ContentView: View {
    @Environment(\.authManager) private var authManager
    @Environment(\.kgService) private var kgService
    @Environment(\.modelContext) private var modelContext
    @Environment(\.networkMonitor) private var networkMonitor

    var body: some View {
        VStack(spacing: 0) {
            if authManager.isDemoMode {
                DemoBanner {
                    authManager.exitDemoMode(modelContainer: modelContext.container)
                }
            }

            if !networkMonitor.isConnected {
                AppBanner(message: "目前沒有網路連線", systemImage: "wifi.slash")
            }

            if let syncError = kgService.lastBackgroundSyncError, networkMonitor.isConnected {
                AppBanner(
                    message: syncError,
                    systemImage: "arrow.triangle.2.circlepath.circle",
                    onDismiss: { kgService.lastBackgroundSyncError = nil }
                )
            }

            TabView {
                Tab("書庫".localized, systemImage: "books.vertical") {
                    BookshelfView()
                }
                Tab("生詞庫".localized, systemImage: "character.book.closed") {
                    NotebookListView()
                }
                Tab("總覽".localized, systemImage: "chart.bar") {
                    OverviewTab()
                }
            }
            .tabViewStyle(.tabBarOnly)
        }
        .animatePhaseChange(networkMonitor.isConnected)
        .animatePhaseChange(authManager.isDemoMode)
        .animatePhaseChange(kgService.lastBackgroundSyncError == nil)
    }
}

#Preview {
    ContentView()
        .modelContainer(for: [Book.self, VocabularyEntry.self, Notebook.self, ReviewRecord.self], inMemory: true)
}
