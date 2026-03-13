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
                OfflineBanner()
            }

            if let syncError = kgService.lastBackgroundSyncError, networkMonitor.isConnected {
                SyncErrorBanner(message: syncError) {
                    kgService.lastBackgroundSyncError = nil
                }
            }

            TabView {
                Tab("書庫".localized, systemImage: "books.vertical") {
                    BookshelfView()
                }
                Tab("生詞庫".localized, systemImage: "character.book.closed") {
                    VocabularyListView()
                }
            }
            .tabViewStyle(.tabBarOnly)
        }
        .animation(AppMotion.phaseChange, value: networkMonitor.isConnected)
        .animation(AppMotion.phaseChange, value: authManager.isDemoMode)
        .animation(AppMotion.phaseChange, value: kgService.lastBackgroundSyncError == nil)
    }
}

#Preview {
    ContentView()
        .modelContainer(for: [Book.self, VocabularyEntry.self], inMemory: true)
}
