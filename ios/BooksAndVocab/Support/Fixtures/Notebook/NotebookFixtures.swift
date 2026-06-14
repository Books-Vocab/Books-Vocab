#if os(iOS)
import Foundation
import SwiftData

enum NotebookFixtureID: String, CaseIterable {
    case coverGallery
    case empty
    case populated
    case readerPickerMany
    case readerPickerPopulated
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
    let color: String?
    let coverPattern: String?
    let coverImageAssetRef: String?
    let syncStatus: Int
    let isDefault: Bool
    let sortOrder: Int
    let entries: [NotebookEntrySeed]
}

struct NotebookFixtureSeed: Codable {
    let notebooks: [NotebookSeed]
}

struct NotebookFixtureRenderModel {
    let notebooks: [Notebook]
    let container: ModelContainer
}

enum NotebookFixtures {
    private static let sharedSurfaces: Set<FixtureSurface> = [.preview, .catalog, .snapshot]

    private static let registry = FixtureRegistry<NotebookFixtureSeed>(
        NotebookFixtureID.allCases.map { fixtureID in
            FixtureRecipe(key: fixtureID.key, surfaces: surfaces(for: fixtureID), tags: tags(for: fixtureID)) {
                FixtureDatasetStore.requireNotebookSeed(for: fixtureID)
            }
        }
    )

    private static func surfaces(for fixtureID: NotebookFixtureID) -> Set<FixtureSurface> {
        switch fixtureID {
        case .coverGallery:
            return [.catalog, .snapshot]
        case .empty, .populated, .readerPickerMany, .readerPickerPopulated, .single:
            return sharedSurfaces
        }
    }

    private static func tags(for fixtureID: NotebookFixtureID) -> Set<String> {
        switch fixtureID {
        case .coverGallery:
            return ["cover"]
        case .empty, .populated, .readerPickerMany, .readerPickerPopulated, .single:
            return ["baseline"]
        }
    }

    static func recipes(for surface: FixtureSurface) -> [FixtureRecipe<NotebookFixtureSeed>] {
        registry.recipes(for: surface)
    }

    @MainActor
    static func renderModel(for fixtureID: NotebookFixtureID) -> NotebookFixtureRenderModel {
        let seed = FixtureDatasetStore.requireNotebookSeed(for: fixtureID)
        do {
            let notebooks = try seed.notebooks.map(makeNotebook(from:))
            return .init(
                notebooks: notebooks,
                container: try makeContainer(from: seed)
            )
        } catch {
            preconditionFailure("Failed to materialize UI World notebook.\(fixtureID.rawValue): \(error)")
        }
    }

    @MainActor
    static func notebooks(for fixtureID: NotebookFixtureID) -> [Notebook] {
        let seed = FixtureDatasetStore.requireNotebookSeed(for: fixtureID)
        do {
            return try seed.notebooks.map(makeNotebook(from:))
        } catch {
            preconditionFailure("Failed to materialize UI World notebook.\(fixtureID.rawValue): \(error)")
        }
    }

    @MainActor
    private static func makeContainer(from seed: NotebookFixtureSeed) throws -> ModelContainer {
        let schema = Schema([Notebook.self, VocabularyEntry.self])
        let config = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        let container = try ModelContainer(for: schema, configurations: config)
        let context = ModelContext(container)
        for notebookSeed in seed.notebooks {
            context.insert(try makeNotebook(from: notebookSeed))
            for entrySeed in notebookSeed.entries {
                context.insert(makeEntry(from: entrySeed, notebookId: notebookSeed.remoteId))
            }
        }
        try context.save()
        return container
    }

    private static func makeNotebook(from seed: NotebookSeed) throws -> Notebook {
        let notebook = Notebook(remoteId: seed.remoteId, name: seed.name, color: seed.color, isDefault: seed.isDefault)
        notebook.coverPattern = seed.coverPattern
        if let ref = seed.coverImageAssetRef {
            let installedURL = try FixtureDatasetStore.requireInstalledAssetURL(ref: ref)
            notebook.coverImagePath = installedURL.path
        }
        notebook.sortOrder = seed.sortOrder
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
