#if DEBUG && canImport(Playbook)
import Playbook
import SwiftData
import SwiftUI

/// Catalog scenarios for the full `SettingsView` surface (設定).
///
/// `SettingsView` is `@Query`-backed over synced `VocabularyEntry`
/// (`syncStatus == 1 && actionType != "delete" && isArchived == false`) and
/// renders `SettingsPresenter(state:)`. Its `.task(id: isLoggedIn)` calls
/// `coordinator.loadData` (whose only network touch is an async
/// `kgService.healthCheck()` — harmless against the disposable preview service
/// and non-blocking for the first render) and `subscriptionManager.refresh`,
/// which self-no-ops to default entitlements when logged out. With the
/// env-default logged-out `AuthManager.shared`, the account section renders its
/// signed-out CTA — the honest default catalog state. Requires both
/// `AppAppearanceStore` and `AppLanguageStore` as `@EnvironmentObject`. Seeding
/// runs in a (nonisolated) scene `init`; safe under Playbook's main-thread
/// rendering (mirrors `StatsViewScene`).
enum SettingsViewScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Settings View") {
            Scenario("Signed out · with vocab", layout: .fill) {
                SettingsViewScene(entryCount: 42)
            }
            Scenario("Signed out · zero data", layout: .fill) {
                SettingsViewScene(entryCount: 0)
            }
        }
    }
}

// MARK: - Scene harness

@MainActor
func makeSettingsCatalogContainer(entryCount: Int) throws -> ModelContainer {
    let container = try ModelContainer(
        for: VocabularyEntry.self, ReviewRecord.self, Notebook.self,
        configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
    )
    let context = container.mainContext
    for i in 0..<entryCount {
        let entry = VocabularyEntry(
            word: "word\(i)",
            translation: "翻譯\(i)",
            context: "Context line \(i).",
            explanation: "Gloss \(i).",
            partOfSpeech: "n.",
            bookTitle: "Sample Book",
            chapterTitle: "第一章"
        )
        entry.syncStatus = VocabularySyncState.synced.rawValue
        entry.actionType = VocabularySyncAction.add.rawValue
        context.insert(entry)
    }
    try? context.save()
    return container
}

private struct SettingsViewScene: View {
    let container: ModelContainer

    init(entryCount: Int) {
        self.container = try! makeSettingsCatalogContainer(entryCount: entryCount)
    }

    var body: some View {
        AppThemeContainer {
            SettingsView()
                .modelContainer(container)
        }
        .environmentObject(AppAppearanceStore.preview)
        .environmentObject(AppLanguageStore.preview)
    }
}
#endif
