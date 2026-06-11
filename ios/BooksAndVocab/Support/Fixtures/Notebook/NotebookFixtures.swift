#if os(iOS)
import Foundation
import SwiftData

enum NotebookFixtureID: String, CaseIterable {
    case populated
    case single

    var key: FixtureKey {
        FixtureKey("notebook.\(rawValue)")
    }
}

struct NotebookEntrySeed: Codable {
    let word: String
    let translation: String
    var context: String?
    var explanation: String?
    var partOfSpeech: String?
    var bookTitle: String?
    var chapterTitle: String?
}

struct NotebookSeed: Codable {
    let remoteId: String
    let name: String
    var isDefault: Bool?
    var sortOrder: Int?
    let entries: [NotebookEntrySeed]
}

struct NotebookFixtureSeed: Codable {
    let notebooks: [NotebookSeed]
}

struct NotebookFixtureRenderModel {
    let notebooks: [Notebook]
    let container: ModelContainer?
}

enum NotebookFixtures {
    private static let sharedSurfaces: Set<FixtureSurface> = [.preview, .catalog, .snapshot]

    private static let defaultNotebook = NotebookSeed(
        remoteId: "default",
        name: "我的單字本",
        isDefault: true,
        sortOrder: 0,
        entries: [
            .init(word: "serendipity", translation: "機緣巧合"),
            .init(word: "ephemeral", translation: "短暫的"),
            .init(word: "petrichor", translation: "雨後泥土香"),
        ]
    )

    private static let registry = FixtureRegistry<NotebookFixtureSeed>([
        FixtureRecipe(key: NotebookFixtureID.populated.key, surfaces: sharedSurfaces, tags: ["baseline"]) {
            .init(notebooks: [
                defaultNotebook,
                NotebookSeed(
                    remoteId: "nb-classics",
                    name: "經典文學",
                    sortOrder: 1,
                    entries: [
                        .init(word: "melancholy", translation: "憂鬱"),
                        .init(word: "sublime", translation: "崇高的"),
                    ]
                ),
                NotebookSeed(
                    remoteId: "nb-science",
                    name: "科普閱讀",
                    sortOrder: 2,
                    entries: [
                        .init(word: "entropy", translation: "熵"),
                    ]
                ),
            ])
        },
        FixtureRecipe(key: NotebookFixtureID.single.key, surfaces: sharedSurfaces, tags: ["baseline"]) {
            .init(notebooks: [defaultNotebook])
        },
    ])

    static func recipes(for surface: FixtureSurface) -> [FixtureRecipe<NotebookFixtureSeed>] {
        registry.recipes(for: surface)
    }

    @MainActor
    static func renderModel(for fixtureID: NotebookFixtureID) -> NotebookFixtureRenderModel {
        let seed = FixtureDatasetStore.notebookSeed(for: fixtureID)
            ?? registry.recipe(for: fixtureID.key).build()
        let notebooks = seed.notebooks.map(makeNotebook(from:))
        return .init(
            notebooks: notebooks,
            container: makeContainer(from: seed)
        )
    }

    @MainActor
    private static func makeContainer(from seed: NotebookFixtureSeed) -> ModelContainer? {
        let schema = Schema([Notebook.self, VocabularyEntry.self])
        let config = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        do {
            let container = try ModelContainer(for: schema, configurations: config)
            let context = ModelContext(container)
            for notebookSeed in seed.notebooks {
                context.insert(makeNotebook(from: notebookSeed))
                for entrySeed in notebookSeed.entries {
                    context.insert(makeEntry(from: entrySeed, notebookId: notebookSeed.remoteId))
                }
            }
            try? context.save()
            return container
        } catch {
            AppLog.app.warning("NotebookFixtures container failed: \(error.localizedDescription)")
            return nil
        }
    }

    private static func makeNotebook(from seed: NotebookSeed) -> Notebook {
        let notebook = Notebook(remoteId: seed.remoteId, name: seed.name, isDefault: seed.isDefault ?? false)
        notebook.sortOrder = seed.sortOrder ?? 0
        notebook.syncStatus = 1
        return notebook
    }

    private static func makeEntry(from seed: NotebookEntrySeed, notebookId: String) -> VocabularyEntry {
        let entry = VocabularyEntry(
            word: seed.word,
            translation: seed.translation,
            context: seed.context ?? "A sentence using \(seed.word).",
            explanation: seed.explanation ?? "A short gloss for \(seed.word).",
            partOfSpeech: seed.partOfSpeech ?? "n.",
            bookTitle: seed.bookTitle ?? "Sample Book",
            chapterTitle: seed.chapterTitle ?? "第一章"
        )
        entry.notebookId = notebookId
        entry.isArchived = false
        entry.syncStatus = VocabularySyncState.synced.rawValue
        entry.actionType = VocabularySyncAction.add.rawValue
        return entry
    }
}
#endif
