//
//  ContentView.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/24.
//

import SwiftUI
import SwiftData
import Inject

/// 主介面 — Tab 導航
struct ContentView: View {
    @Environment(\.authManager) private var authManager
    @Environment(\.modelContext) private var modelContext

    // Why: Hot-reload hook. Release builds: LLVM-strip 成 no-op，零 runtime cost。
    // 詳見 docs/sop/ios.md §Hot Reload。
    @ObserveInjection private var inject

    var body: some View {
        VStack(spacing: 0) {
            if authManager.isDemoMode {
                DemoBanner {
                    authManager.exitDemoMode(modelContainer: modelContext.container)
                }
            }

            TabView {
                #if os(iOS)
                BookshelfView()
                    .tabItem { Label("書庫".localized, systemImage: "books.vertical") }
                #endif
                NotebookListView()
                    .tabItem { Label("單字本".localized, systemImage: "character.book.closed") }
                OverviewTab()
                    .tabItem { Label("總覽".localized, systemImage: "chart.bar") }
            }
        }
        .appOfflineBanner()
        .animatePhaseChange(authManager.isDemoMode)
        .enableInjection()
    }
}

#Preview {
    ContentView()
        .modelContainer(for: [Book.self, VocabularyEntry.self, Notebook.self, ReviewRecord.self], inMemory: true)
}
