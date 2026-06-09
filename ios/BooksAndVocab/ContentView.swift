//
//  ContentView.swift
//  Books & Vocab
//
//  Created by 陳亮宇 on 2026/2/24.
//

import SwiftUI
import SwiftData

enum AppPrimarySection: String, CaseIterable, Identifiable, Equatable {
    case bookshelf
    case podcasts
    case notebooks
    case overview

    var id: String { rawValue }

    var titleKey: String {
        switch self {
        case .bookshelf: return "app.section.bookshelf"
        case .podcasts: return "app.section.podcasts"
        case .notebooks: return "app.section.notebooks"
        case .overview: return "app.section.overview"
        }
    }

    var systemImage: String {
        switch self {
        case .bookshelf: return "books.vertical"
        case .podcasts: return "waveform"
        case .notebooks: return "character.book.closed"
        case .overview: return "chart.bar"
        }
    }
}

/// 主介面 — Tab 導航
struct ContentView: View {
    @Environment(\.authManager) private var authManager
    @Environment(\.modelContext) private var modelContext
    @State private var selectedSection: AppPrimarySection = .bookshelf

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

            primaryNavigation
        }
        .appOfflineBanner()
        .animatePhaseChange(authManager.isDemoMode)
        .macWindowChrome()
        .enableInjection()
    }

    @ViewBuilder
    private var primaryNavigation: some View {
        #if targetEnvironment(macCatalyst)
        NavigationSplitView {
            List {
                ForEach(AppPrimarySection.allCases) { section in
                    AppSidebarRow(
                        systemImage: section.systemImage,
                        title: L10n.string(section.titleKey),
                        isSelected: selectedSection == section,
                        action: { selectedSection = section }
                    )
                    .listRowBackground(Color.clear)
                    .listRowInsets(EdgeInsets())
                }
            }
            .listStyle(.sidebar)
            .navigationTitle("KG")
        } detail: {
            sectionContent(selectedSection)
                .id(selectedSection)
        }
        .navigationSplitViewStyle(.balanced)
        #else
        TabView {
            #if os(iOS)
            BookshelfView()
                .tabItem { Label(L10n.string(AppPrimarySection.bookshelf.titleKey), systemImage: AppPrimarySection.bookshelf.systemImage) }
                .accessibilityIdentifier("tab.bookshelf")
            #endif
            PodcastHomeView()
                .tabItem { Label(L10n.string(AppPrimarySection.podcasts.titleKey), systemImage: AppPrimarySection.podcasts.systemImage) }
                .accessibilityIdentifier("tab.podcasts")
            NotebookListView()
                .tabItem { Label(L10n.string(AppPrimarySection.notebooks.titleKey), systemImage: AppPrimarySection.notebooks.systemImage) }
                .accessibilityIdentifier("tab.notebooks")
            OverviewTab()
                .tabItem { Label(L10n.string(AppPrimarySection.overview.titleKey), systemImage: AppPrimarySection.overview.systemImage) }
                .accessibilityIdentifier("tab.overview")
        }
        #endif
    }

    @ViewBuilder
    private func sectionContent(_ section: AppPrimarySection) -> some View {
        switch section {
        case .bookshelf:
            // sectionContent is only invoked from the macCatalyst NavigationSplitView
            // branch, where os(iOS) is always true — the #else was dead code.
            BookshelfView()
        case .podcasts:
            PodcastHomeView()
        case .notebooks:
            NotebookListView()
        case .overview:
            OverviewTab()
        }
    }
}

#Preview {
    ContentView()
        .modelContainer(for: [Book.self, VocabularyEntry.self, Notebook.self, ReviewRecord.self], inMemory: true)
}
