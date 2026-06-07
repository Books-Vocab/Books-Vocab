#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `VocabularyListToolbar` (`VocabularyListView+Toolbar.swift`).
///
/// The toolbar is a `ViewModifier` injecting a sync glyph (with pending badge /
/// pulse) and an export `Menu`. It is hosted inside a `NavigationStack` so the
/// `.toolbar` content actually renders, and driven entirely by synthetic value
/// inputs + no-op closures.
enum VocabularyListToolbarScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Vocabulary List Toolbar") {
            Scenario("Idle · synced entries", layout: .fill) {
                ToolbarScene(
                    isLoggedIn: true,
                    isSyncing: false,
                    pendingCount: 0,
                    hasSyncedEntries: true
                )
            }
            Scenario("Pending badge", layout: .fill) {
                ToolbarScene(
                    isLoggedIn: true,
                    isSyncing: false,
                    pendingCount: 7,
                    hasSyncedEntries: true
                )
            }
            Scenario("Pending stress (99+)", layout: .fill) {
                ToolbarScene(
                    isLoggedIn: true,
                    isSyncing: false,
                    pendingCount: 128,
                    hasSyncedEntries: true
                )
            }
            Scenario("Syncing (pulse)", layout: .fill) {
                ToolbarScene(
                    isLoggedIn: true,
                    isSyncing: true,
                    pendingCount: 3,
                    hasSyncedEntries: true
                )
            }
            Scenario("No synced entries (export hidden)", layout: .fill) {
                ToolbarScene(
                    isLoggedIn: false,
                    isSyncing: false,
                    pendingCount: 0,
                    hasSyncedEntries: false
                )
            }
        }
    }
}

// MARK: - Scene harness

private struct ToolbarScene: View {
    let isLoggedIn: Bool
    let isSyncing: Bool
    let pendingCount: Int
    let hasSyncedEntries: Bool

    var body: some View {
        AppThemeContainer {
            NavigationStack {
                List {
                    Text("serendipity")
                    Text("epiphany")
                    Text("revelation")
                }
                .navigationTitle("詞彙")
                .modifier(
                    VocabularyListToolbar(
                        isLoggedIn: isLoggedIn,
                        isSyncing: isSyncing,
                        pendingCount: pendingCount,
                        onSync: {},
                        onExportCSV: {},
                        onExportJSON: {},
                        onExportAnki: {},
                        hasSyncedEntries: hasSyncedEntries
                    )
                )
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
