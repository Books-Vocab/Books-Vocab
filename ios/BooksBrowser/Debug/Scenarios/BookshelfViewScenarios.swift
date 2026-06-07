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
                BookshelfViewScene(fixture: .populated)
            }
            Scenario("Single book", layout: .fill) {
                BookshelfViewScene(fixture: .single)
            }
            Scenario("Empty shelf", layout: .fill) {
                BookshelfViewScene(fixture: .empty)
            }
        }
    }
}

// MARK: - Fixtures

private enum BookshelfViewFixture {
    case populated
    case single
    case empty
}

// MARK: - Scene harness

private struct BookshelfViewScene: View {
    let container: ModelContainer

    init(fixture: BookshelfViewFixture) {
        let container = try! ModelContainer(
            for: Book.self, Notebook.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        )
        let context = container.mainContext
        Self.seed(fixture, into: context)
        try? context.save()
        self.container = container
    }

    var body: some View {
        AppThemeContainer {
            BookshelfView()
                .modelContainer(container)
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    // MARK: Seeding

    private static func book(
        title: String,
        author: String,
        format: BookFormat,
        daysAgo: Int
    ) -> Book {
        let book = Book(title: title, author: author, fileName: "\(title).\(format.rawValue)", format: format)
        let cal = Calendar.current
        book.dateLastRead = cal.date(byAdding: .day, value: -daysAgo, to: Date())
        return book
    }

    private static func seed(_ fixture: BookshelfViewFixture, into context: ModelContext) {
        switch fixture {
        case .empty:
            return
        case .single:
            context.insert(book(title: "Atomic Habits", author: "James Clear", format: .epub, daysAgo: 0))
        case .populated:
            context.insert(book(title: "Atomic Habits", author: "James Clear", format: .epub, daysAgo: 0))
            context.insert(book(title: "Deep Work", author: "Cal Newport", format: .pdf, daysAgo: 2))
            context.insert(book(title: "Flow", author: "Mihaly Csikszentmihalyi", format: .epub, daysAgo: 5))
            context.insert(book(title: "Meditations", author: "Marcus Aurelius", format: .txt, daysAgo: 9))
            context.insert(book(title: "On Writing Well", author: "William Zinsser", format: .md, daysAgo: 14))
        }
    }
}
#endif
