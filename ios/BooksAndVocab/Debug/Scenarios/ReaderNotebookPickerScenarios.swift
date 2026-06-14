#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI
import SwiftData

/// Catalog scenarios for `ReaderNotebookPicker` — the in-reader sheet that binds
/// the current book to a target notebook (or "follow global").
///
/// The picker is `@Query`-backed over `Notebook` and reads `@Environment(\.modelContext)`,
/// so each scenario materializes UI World notebook + bookshelf seeds into one
/// in-memory `ModelContainer`. Missing seed, stale book binding, or save failure
/// fail at catalog construction time.
enum ReaderNotebookPickerScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Reader Notebook Picker") {
            Scenario("With notebooks · follow global", layout: .fill) {
                ReaderNotebookPickerScene(fixture: .populatedUnbound)
            }
            Scenario("With notebooks · one bound", layout: .fill) {
                ReaderNotebookPickerScene(fixture: .populatedBound)
            }
            Scenario("Many notebooks (stress)", layout: .fill) {
                ReaderNotebookPickerScene(fixture: .manyBound)
            }
            Scenario("Empty — no notebooks", layout: .fill) {
                ReaderNotebookPickerScene(fixture: .empty)
            }
        }
    }
}

// MARK: - Fixtures

private enum ReaderNotebookPickerFixture {
    case populatedUnbound
    case populatedBound
    case manyBound
    case empty

    var notebookID: NotebookFixtureID {
        switch self {
        case .populatedUnbound, .populatedBound:
            return .readerPickerPopulated
        case .manyBound:
            return .readerPickerMany
        case .empty:
            return .empty
        }
    }

    var bookshelfID: BookshelfFixtureID {
        switch self {
        case .populatedUnbound:
            return .readerNotebookUnbound
        case .populatedBound:
            return .readerNotebookBound
        case .manyBound:
            return .readerNotebookLongBound
        case .empty:
            return .readerNotebookEmpty
        }
    }

    var expectedNotebookCount: Int {
        switch self {
        case .populatedUnbound, .populatedBound:
            return 3
        case .manyBound:
            return 14
        case .empty:
            return 0
        }
    }
}

// MARK: - Scene harness

private struct ReaderNotebookPickerScene: View {
    private let container: ModelContainer
    private let book: Book

    init(fixture: ReaderNotebookPickerFixture) {
        let payload = MainActor.assumeIsolated {
            Self.materialize(fixture: fixture)
        }
        container = payload.container
        book = payload.book
    }

    var body: some View {
        AppThemeContainer {
            ReaderNotebookPicker(book: book)
                .modelContainer(container)
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    @MainActor
    private static func materialize(fixture: ReaderNotebookPickerFixture) -> (container: ModelContainer, book: Book) {
        let notebooks = NotebookFixtures.notebooks(for: fixture.notebookID)
        let books = BookshelfFixtures.books(for: fixture.bookshelfID)
        precondition(
            notebooks.count == fixture.expectedNotebookCount,
            "UI World notebook.\(fixture.notebookID.rawValue) expected \(fixture.expectedNotebookCount) notebooks, got \(notebooks.count)"
        )
        precondition(
            books.count == 1,
            "UI World bookshelf.\(fixture.bookshelfID.rawValue) expected exactly one reader book, got \(books.count)"
        )

        let book = books[0]
        if let boundId = book.preferredNotebookId {
            precondition(
                notebooks.contains { $0.remoteId == boundId },
                "UI World bookshelf.\(fixture.bookshelfID.rawValue) binds book to missing notebook \(boundId)"
            )
        }

        do {
            let container = try ModelContainer(
                for: Book.self, Notebook.self,
                configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
            )
            let context = container.mainContext
            for notebook in notebooks {
                context.insert(notebook)
            }
            context.insert(book)
            try context.save()
            return (container, book)
        } catch {
            preconditionFailure("Failed to materialize UI World reader notebook picker fixture: \(error)")
        }
    }
}
#endif
