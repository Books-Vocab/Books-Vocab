#if DEBUG && canImport(Playbook)
import Playbook
import SwiftData
import SwiftUI

/// Catalog scenarios for the full `SyncView` surface (待同步單字審閱).
///
/// `SyncView` is `@Query`-backed over `VocabularyEntry` (`syncStatus != 1`, i.e.
/// not yet synced) and renders `SyncPresenter(state:)`. Its `.task` only calls
/// `refreshStepLayoutIfIdle()` — pure local layout, no network — so the view is
/// fully catalogable by seeding a fresh in-memory store. `presenterState` reads
/// `authManager.isLoggedIn` / `kgService.isConnected`; we inject a logged-out
/// `CatalogPreviewAuth` so the rendering is deterministic instead of depending on
/// the simulator's persisted `AuthManager.shared` session. Seeding happens inside a (nonisolated) View
/// scene whose `init` touches `mainContext`; safe because Playbook renders on the
/// main thread (mirrors `StatsViewScene`).
enum SyncViewScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Sync View") {
            Scenario("Pending · adds + deletes", layout: .fill) {
                SyncViewScene(fixture: .mixed)
            }
            Scenario("Pending · single add", layout: .fill) {
                SyncViewScene(fixture: .single)
            }
            Scenario("Empty · nothing pending", layout: .fill) {
                SyncViewScene(fixture: .empty)
            }
        }
    }
}

// MARK: - Fixtures

private enum SyncViewFixture {
    case mixed
    case single
    case empty
}

// MARK: - Scene harness

private struct SyncViewScene: View {
    let container: ModelContainer

    init(fixture: SyncViewFixture) {
        let container = try! ModelContainer(
            for: VocabularyEntry.self, Notebook.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        )
        let context = container.mainContext
        Self.seed(fixture, into: context)
        try? context.save()
        self.container = container
    }

    var body: some View {
        AppThemeContainer {
            SyncView()
                .modelContainer(container)
                .environment(\.authManager, CatalogPreviewAuth(isLoggedIn: false))
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    // MARK: Seeding

    /// A pending (unsynced) entry: `syncStatus = pending` so it passes the
    /// `syncStatus != 1` query; `actionType` drives add vs delete grouping.
    private static func pending(
        word: String,
        translation: String,
        action: VocabularySyncAction
    ) -> VocabularyEntry {
        let entry = VocabularyEntry(
            word: word,
            translation: translation,
            context: "A line of context featuring \(word) in situ.",
            explanation: "A short gloss for \(word).",
            partOfSpeech: "n.",
            bookTitle: "Sample Book",
            chapterTitle: "第一章"
        )
        entry.syncStatus = VocabularySyncState.pending.rawValue
        entry.actionType = action.rawValue
        return entry
    }

    private static func seed(_ fixture: SyncViewFixture, into context: ModelContext) {
        switch fixture {
        case .empty:
            return
        case .single:
            context.insert(pending(word: "serendipity", translation: "機緣巧合", action: .add))
        case .mixed:
            context.insert(pending(word: "ephemeral", translation: "短暫的", action: .add))
            context.insert(pending(word: "luminous", translation: "發光的", action: .add))
            context.insert(pending(word: "petrichor", translation: "雨後泥土香", action: .add))
            context.insert(pending(word: "obsolete", translation: "過時的", action: .delete))
        }
    }
}
#endif
