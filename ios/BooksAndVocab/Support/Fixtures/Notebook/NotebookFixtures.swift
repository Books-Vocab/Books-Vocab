#if os(iOS)
import Foundation
import SwiftData

enum NotebookFixtureID: String, CaseIterable {
    case cardGallery
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
    let cardState: NotebookCardStateSeed?
    let syncStatus: Int
    let isDefault: Bool
    let sortOrder: Int
    let entries: [NotebookEntrySeed]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case remoteId
        case name
        case color
        case coverPattern
        case coverImageAssetRef
        case cardState
        case syncStatus
        case isDefault
        case sortOrder
        case entries
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                DecodingError.Context(
                    codingPath: container.codingPath,
                    debugDescription: "UI World notebook row must explicitly declare \(key.rawValue)"
                )
            )
        }
        remoteId = try container.decode(String.self, forKey: .remoteId)
        name = try container.decode(String.self, forKey: .name)
        color = try container.decodeIfPresent(String.self, forKey: .color)
        coverPattern = try container.decodeIfPresent(String.self, forKey: .coverPattern)
        coverImageAssetRef = try container.decodeIfPresent(String.self, forKey: .coverImageAssetRef)
        cardState = try container.decodeIfPresent(NotebookCardStateSeed.self, forKey: .cardState)
        syncStatus = try container.decode(Int.self, forKey: .syncStatus)
        isDefault = try container.decode(Bool.self, forKey: .isDefault)
        sortOrder = try container.decode(Int.self, forKey: .sortOrder)
        entries = try container.decode([NotebookEntrySeed].self, forKey: .entries)
    }
}

struct NotebookCardStateSeed: Codable {
    let cardCount: Int
    let dueCount: Int
    let unlearnedCount: Int
    let reviewedCount: Int
    let pendingCount: Int
    let lastActivity: Date?
    let isActive: Bool
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
        case .cardGallery, .coverGallery:
            return [.catalog, .snapshot]
        case .empty, .populated, .readerPickerMany, .readerPickerPopulated, .single:
            return sharedSurfaces
        }
    }

    private static func tags(for fixtureID: NotebookFixtureID) -> Set<String> {
        switch fixtureID {
        case .cardGallery:
            return ["card"]
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
    static func cardData(for fixtureID: NotebookFixtureID) -> [NotebookCardData] {
        let seed = FixtureDatasetStore.requireNotebookSeed(for: fixtureID)
        return seed.notebooks.map { notebook in
            guard let cardState = notebook.cardState else {
                preconditionFailure("UI World notebook.\(fixtureID.rawValue).\(notebook.remoteId) is missing cardState")
            }
            let syncedTotal = cardState.dueCount + cardState.unlearnedCount + cardState.reviewedCount
            precondition(
                cardState.cardCount == syncedTotal,
                "UI World notebook.\(fixtureID.rawValue).\(notebook.remoteId) cardCount \(cardState.cardCount) must equal due + unlearned + reviewed \(syncedTotal)"
            )
            return NotebookCardData(
                name: notebook.name,
                color: notebook.color,
                coverPattern: notebook.coverPattern,
                coverImagePath: nil,
                cardCount: cardState.cardCount,
                dueCount: cardState.dueCount,
                unlearnedCount: cardState.unlearnedCount,
                reviewedCount: cardState.reviewedCount,
                pendingCount: cardState.pendingCount,
                lastActivity: cardState.lastActivity,
                isActive: cardState.isActive
            )
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
