#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI
import SwiftData

/// Catalog scenarios for `ReaderNotebookPicker` — the in-reader sheet that binds
/// the current book to a target notebook (or "follow global").
///
/// The picker is `@Query`-backed over `Notebook` and reads `@Environment(\.modelContext)`,
/// so each scenario seeds an in-memory `ModelContainer` with synthetic notebooks + a book.
/// Container construction + model insertion touch `@MainActor`, so all seeding happens
/// inside a `@MainActor` `View` scene struct (`body` is main-actor isolated).
enum ReaderNotebookPickerScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Reader Notebook Picker") {
            Scenario("With notebooks · follow global", layout: .fill) {
                ReaderNotebookPickerScene(
                    notebooks: ReaderNotebookPickerScene.sampleNotebooks,
                    boundRemoteId: nil
                )
            }
            Scenario("With notebooks · one bound", layout: .fill) {
                ReaderNotebookPickerScene(
                    notebooks: ReaderNotebookPickerScene.sampleNotebooks,
                    boundRemoteId: "nb-green"
                )
            }
            Scenario("Many notebooks (stress)", layout: .fill) {
                ReaderNotebookPickerScene(
                    notebooks: ReaderNotebookPickerScene.manyNotebooks,
                    boundRemoteId: "nb-12"
                )
            }
            Scenario("Empty — no notebooks", layout: .fill) {
                ReaderNotebookPickerScene(
                    notebooks: [],
                    boundRemoteId: nil
                )
            }
        }
    }
}

// MARK: - Scene harness

/// Builds an in-memory store, seeds the supplied notebooks + a single book, then
/// presents `ReaderNotebookPicker`. Seeding runs in this struct's `init`; the
/// struct stays nonisolated so the `Scenario { ... }` closure (also nonisolated)
/// can construct it. This is safe because Playbook drives all rendering on the
/// main thread, so `mainContext` is only ever touched there. (Cannot mark the
/// struct `@MainActor`: that would make `init` main-actor-isolated and the
/// nonisolated Scenario closure could no longer call it.)
private struct ReaderNotebookPickerScene: View {
    private let container: ModelContainer
    private let book: Book

    init(notebooks: [(remoteId: String, name: String, color: String?, isDefault: Bool)], boundRemoteId: String?) {
        let container = try! ModelContainer(
            for: Book.self, Notebook.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        )
        let context = container.mainContext

        for (index, spec) in notebooks.enumerated() {
            let notebook = Notebook(
                remoteId: spec.remoteId,
                name: spec.name,
                color: spec.color,
                isDefault: spec.isDefault
            )
            notebook.sortOrder = index
            context.insert(notebook)
        }

        let book = Book(
            title: "The Sample Book",
            author: "Anon",
            fileName: "sample.epub"
        )
        book.preferredNotebookId = boundRemoteId
        context.insert(book)

        self.container = container
        self.book = book
    }

    var body: some View {
        AppThemeContainer {
            ReaderNotebookPicker(book: book)
                .modelContainer(container)
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    // MARK: Fixtures

    static let sampleNotebooks: [(remoteId: String, name: String, color: String?, isDefault: Bool)] = [
        ("nb-default", "我的單字本", nil, true),
        ("nb-green", "綠野仙蹤生詞", "#2E8B57", false),
        ("nb-blue", "商業英文", "#3B6FD4", false),
    ]

    static let manyNotebooks: [(remoteId: String, name: String, color: String?, isDefault: Bool)] = {
        let palette = ["#E0533B", "#2E8B57", "#3B6FD4", "#C9A227", "#7A4FD0"]
        return (1...14).map { i in
            (
                remoteId: "nb-\(i)",
                name: "單字本 #\(i) — 長標題測試截斷行為的範例文字",
                color: palette[i % palette.count],
                isDefault: i == 1
            )
        }
    }()
}
#endif
