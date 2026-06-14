#if DEBUG && canImport(Playbook)
import Playbook
import SwiftData
import SwiftUI

/// Catalog scenarios for the full `BookshelfView` surface (書架).
///
/// `BookshelfView` is `@Query`-backed over `Book` (sorted by `dateLastRead`),
/// driven by a default `BookshelfCoordinator` whose initial state is
/// `isLoading == false` with no error — so the grid renders straight off the
/// seeded store. All side-effecting work (import / login) is user-triggered,
/// not on-appear, so no network fires during a static snapshot. Env-default
/// services (import service, file manager, toast, auth, KGService) resolve on
/// the main actor before the `@Query` read. Seeding runs in a (nonisolated)
/// scene `init` touching `mainContext`; safe under Playbook's main-thread
/// rendering (mirrors `StatsViewScene`).
enum BookshelfViewScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Bookshelf View") {
            Scenario("Populated · mixed formats", layout: .fill) {
                BookshelfViewScene(fixture: .withBooksLibrary)
            }
            Scenario("Single book", layout: .fill) {
                BookshelfViewScene(fixture: .progressCard)
            }
            Scenario("Empty shelf", layout: .fill) {
                BookshelfViewScene(fixture: .emptyLibrary)
            }
        }
    }
}

// MARK: - Scene harness

private struct BookshelfViewScene: View {
    let container: ModelContainer

    init(fixture: BookshelfFixtureID) {
        self.container = BookshelfFixtures.renderModel(for: fixture).container
    }

    var body: some View {
        AppThemeContainer {
            BookshelfView()
                .modelContainer(container)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
