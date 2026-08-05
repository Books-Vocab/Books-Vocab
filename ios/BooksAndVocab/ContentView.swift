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
    case explore

    var id: String { rawValue }

    var titleKey: String {
        switch self {
        case .bookshelf: return "app.section.bookshelf"
        case .podcasts: return "app.section.podcasts"
        case .notebooks: return "app.section.notebooks"
        case .overview: return "app.section.overview"
        case .explore: return "app.section.explore"
        }
    }

    var systemImage: String {
        switch self {
        case .bookshelf: return "books.vertical"
        case .podcasts: return "waveform"
        case .notebooks: return "character.book.closed"
        case .overview: return "chart.bar"
        case .explore: return "sparkles"
        }
    }

    /// Sections the shell actually surfaces (iOS TabView + Catalyst sidebar).
    /// Pure so the feature gates (`KGFeatureFlags.podcastEnabled` — still DEBUG-only;
    /// `.exploreEnabled` — Release-on since 2026-08-05) stay testable without
    /// conditional compilation at every switch site.
    static func visibleCases(podcastEnabled: Bool, exploreEnabled: Bool) -> [AppPrimarySection] {
        allCases.filter { section in
            switch section {
            case .podcasts: return podcastEnabled
            case .explore: return exploreEnabled
            default: return true
            }
        }
    }

    /// Normalizes a selection against the visible set — if a hidden section
    /// (e.g. `.podcasts` with the gate off) ever leaks into selection state,
    /// fall back to the default section instead of a blank detail pane.
    static func resolvedSelection(
        _ selection: AppPrimarySection, podcastEnabled: Bool, exploreEnabled: Bool
    ) -> AppPrimarySection {
        visibleCases(podcastEnabled: podcastEnabled, exploreEnabled: exploreEnabled)
            .contains(selection) ? selection : .bookshelf
    }
}

/// 主介面 — Tab 導航
struct ContentView: View {
    @Environment(\.authManager) private var authManager
    @Environment(\.modelContext) private var modelContext
    @State private var selectedSection: AppPrimarySection = .bookshelf

    private var visibleSections: [AppPrimarySection] {
        AppPrimarySection.visibleCases(
            podcastEnabled: KGFeatureFlags.podcastEnabled,
            exploreEnabled: KGFeatureFlags.exploreEnabled
        )
    }

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
        // KG_PERF shell-domain mark (docs/sop/ui_flow_evidence.md piece 5):
        // one low-frequency event per tab switch, on both iOS TabView and the
        // Catalyst sidebar (single selection source of truth).
        .onChange(of: selectedSection) { _, section in
            PerfLog.shell.mark("tab.selected", "section=\(section.rawValue)")
        }
        // Defensive: selection is plain @State today (no persistence), but if a
        // hidden section ever leaks in (future restoration / deep link), snap
        // back to the default instead of rendering a blank detail pane.
        .onAppear {
            selectedSection = AppPrimarySection.resolvedSelection(
                selectedSection,
                podcastEnabled: KGFeatureFlags.podcastEnabled,
                exploreEnabled: KGFeatureFlags.exploreEnabled
            )
        }
        .animatePhaseChange(authManager.isDemoMode)
        .macWindowChrome()
        .enableInjection()
    }

    @ViewBuilder
    private var primaryNavigation: some View {
        #if targetEnvironment(macCatalyst)
        NavigationSplitView {
            List {
                ForEach(visibleSections) { section in
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
        // selection binding: same @State the Catalyst sidebar drives — keeps one
        // source of truth and lets PerfLog.shell observe tab switches (below).
        TabView(selection: $selectedSection) {
            #if os(iOS)
            BookshelfView()
                .tabItem { Label(L10n.string(AppPrimarySection.bookshelf.titleKey), systemImage: AppPrimarySection.bookshelf.systemImage) }
                .accessibilityIdentifier("tab.bookshelf")
                .tag(AppPrimarySection.bookshelf)
            #endif
            if visibleSections.contains(.podcasts) {
                PodcastHomeView()
                    .tabItem { Label(L10n.string(AppPrimarySection.podcasts.titleKey), systemImage: AppPrimarySection.podcasts.systemImage) }
                    .accessibilityIdentifier("tab.podcasts")
                    .tag(AppPrimarySection.podcasts)
            }
            NotebookListView()
                .tabItem { Label(L10n.string(AppPrimarySection.notebooks.titleKey), systemImage: AppPrimarySection.notebooks.systemImage) }
                .accessibilityIdentifier("tab.notebooks")
                .tag(AppPrimarySection.notebooks)
            OverviewTab()
                .tabItem { Label(L10n.string(AppPrimarySection.overview.titleKey), systemImage: AppPrimarySection.overview.systemImage) }
                .accessibilityIdentifier("tab.overview")
                .tag(AppPrimarySection.overview)
            if visibleSections.contains(.explore) {
                ExploreView()
                    .tabItem { Label(L10n.string(AppPrimarySection.explore.titleKey), systemImage: AppPrimarySection.explore.systemImage) }
                    .accessibilityIdentifier("tab.explore")
                    .tag(AppPrimarySection.explore)
            }
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
        case .explore:
            ExploreView()
        }
    }
}

#Preview {
    ContentView()
        .modelContainer(for: [Book.self, VocabularyEntry.self, Notebook.self, ReviewRecord.self, SharedDeck.self], inMemory: true)
}
