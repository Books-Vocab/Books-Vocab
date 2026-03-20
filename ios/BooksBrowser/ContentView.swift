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

            TabView {
                Tab("書庫".localized, systemImage: "books.vertical") {
                    BookshelfView()
                }
                Tab("單字本".localized, systemImage: "character.book.closed") {
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
    }
}

#Preview {
    ContentView()
        .modelContainer(for: [Book.self, VocabularyEntry.self, Notebook.self, ReviewRecord.self], inMemory: true)
}
