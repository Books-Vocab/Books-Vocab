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
    let syncStatus: Int
    let actionType: String
    let isArchived: Bool
    let isExcludedFromReader: Bool
    let context: String
    let explanation: String?
    let partOfSpeech: String?
    let bookTitle: String
    let chapterTitle: String?

    enum CodingKeys: String, CodingKey, CaseIterable {
        case word
        case translation
        case syncStatus
        case actionType
        case isArchived
        case isExcludedFromReader
        case context
        case explanation
        case partOfSpeech
        case bookTitle
        case chapterTitle
    }

    init(
        word: String,
        translation: String,
        syncStatus: Int,
        actionType: String,
        isArchived: Bool,
        isExcludedFromReader: Bool,
        context: String,
        explanation: String?,
        partOfSpeech: String?,
        bookTitle: String,
        chapterTitle: String?
    ) {
        self.word = word
        self.translation = translation
        self.syncStatus = syncStatus
        self.actionType = actionType
        self.isArchived = isArchived
        self.isExcludedFromReader = isExcludedFromReader
        self.context = context
        self.explanation = explanation
        self.partOfSpeech = partOfSpeech
        self.bookTitle = bookTitle
        self.chapterTitle = chapterTitle
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                DecodingError.Context(
                    codingPath: container.codingPath,
                    debugDescription: "UI World notebook entry must explicitly declare \(key.rawValue)"
                )
            )
        }
        word = try container.decode(String.self, forKey: .word)
        translation = try container.decode(String.self, forKey: .translation)
        syncStatus = try container.decode(Int.self, forKey: .syncStatus)
        actionType = try container.decode(String.self, forKey: .actionType)
        isArchived = try container.decode(Bool.self, forKey: .isArchived)
        isExcludedFromReader = try container.decode(Bool.self, forKey: .isExcludedFromReader)
        context = try container.decode(String.self, forKey: .context)
        explanation = try container.decodeIfPresent(String.self, forKey: .explanation)
        partOfSpeech = try container.decodeIfPresent(String.self, forKey: .partOfSpeech)
        bookTitle = try container.decode(String.self, forKey: .bookTitle)
        chapterTitle = try container.decodeIfPresent(String.self, forKey: .chapterTitle)
    }
}

struct NotebookSeed: Codable {
    let remoteId: String
    let name: String
    let syncStatus: Int
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
        syncStatus: 1,
        isDefault: true,
        sortOrder: 0,
        entries: [
            .init(word: "serendipity", translation: "機緣巧合", syncStatus: 1, actionType: "add", isArchived: false, isExcludedFromReader: false, context: "The trip was pure serendipity.", explanation: "A pleasant discovery made by chance.", partOfSpeech: "n.", bookTitle: "Notebook Fixture", chapterTitle: "Default"),
            .init(word: "ephemeral", translation: "短暫的", syncStatus: 1, actionType: "add", isArchived: false, isExcludedFromReader: false, context: "The morning mist felt ephemeral.", explanation: "Lasting for a very short time.", partOfSpeech: "adj.", bookTitle: "Notebook Fixture", chapterTitle: "Default"),
            .init(word: "petrichor", translation: "雨後泥土香", syncStatus: 1, actionType: "add", isArchived: false, isExcludedFromReader: false, context: "Petrichor filled the street after rain.", explanation: "The earthy smell after rainfall.", partOfSpeech: "n.", bookTitle: "Notebook Fixture", chapterTitle: "Default"),
        ]
    )

    private static let registry = FixtureRegistry<NotebookFixtureSeed>([
        FixtureRecipe(key: NotebookFixtureID.populated.key, surfaces: sharedSurfaces, tags: ["baseline"]) {
            .init(notebooks: [
                defaultNotebook,
                NotebookSeed(
                    remoteId: "nb-classics",
                    name: "經典文學",
                    syncStatus: 1,
                    sortOrder: 1,
                    entries: [
                        .init(word: "melancholy", translation: "憂鬱", syncStatus: 1, actionType: "add", isArchived: false, isExcludedFromReader: false, context: "A quiet melancholy runs through the chapter.", explanation: "A thoughtful sadness.", partOfSpeech: "n.", bookTitle: "Classic Fixture", chapterTitle: "Mood"),
                        .init(word: "sublime", translation: "崇高的", syncStatus: 1, actionType: "add", isArchived: false, isExcludedFromReader: false, context: "The view was sublime.", explanation: "Of exceptional beauty or grandeur.", partOfSpeech: "adj.", bookTitle: "Classic Fixture", chapterTitle: "Mood"),
                    ]
                ),
                NotebookSeed(
                    remoteId: "nb-science",
                    name: "科普閱讀",
                    syncStatus: 1,
                    sortOrder: 2,
                    entries: [
                        .init(word: "entropy", translation: "熵", syncStatus: 1, actionType: "add", isArchived: false, isExcludedFromReader: false, context: "Entropy increases in a closed system.", explanation: "A measure of disorder.", partOfSpeech: "n.", bookTitle: "Science Fixture", chapterTitle: "Systems"),
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
        let seed = FixtureDatasetStore.requireNotebookSeed(for: fixtureID)
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
        notebook.syncStatus = seed.syncStatus
        return notebook
    }

    private static func makeEntry(from seed: NotebookEntrySeed, notebookId: String) -> VocabularyEntry {
        let entry = VocabularyEntry(
            word: seed.word,
            translation: seed.translation,
            context: seed.context,
            explanation: seed.explanation,
            partOfSpeech: seed.partOfSpeech,
            bookTitle: seed.bookTitle,
            chapterTitle: seed.chapterTitle
        )
        entry.notebookId = notebookId
        entry.syncStatus = seed.syncStatus
        entry.actionType = seed.actionType
        entry.isArchived = seed.isArchived
        entry.isExcludedFromReader = seed.isExcludedFromReader
        return entry
    }
}
#endif
