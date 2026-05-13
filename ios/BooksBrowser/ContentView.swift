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
    @Environment(\.modelContext) private var modelContext

    #if os(macOS)
    @State private var showSettings = false
    #endif

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
        #if os(macOS)
        .toolbar {
            ToolbarItem(placement: .automatic) {
                Button {
                    showSettings = true
                } label: {
                    Image(systemName: "gearshape")
                }
            }
        }
        .sheet(isPresented: $showSettings) {
            SettingsView()
        }
        #endif
    }
}

#Preview {
    ContentView()
        .modelContainer(for: [Book.self, VocabularyEntry.self, Notebook.self, ReviewRecord.self], inMemory: true)
}
