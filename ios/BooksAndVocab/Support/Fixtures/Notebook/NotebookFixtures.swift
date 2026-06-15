#if os(iOS)
import Foundation
import SwiftData

private struct AnyNotebookCodingKey: CodingKey {
    let stringValue: String
    let intValue: Int?

    init?(stringValue: String) {
        self.stringValue = stringValue
        self.intValue = nil
    }

    init?(intValue: Int) {
        self.stringValue = "\(intValue)"
        self.intValue = intValue
    }
}

private func rejectUnknownNotebookKeys<K: CodingKey & RawRepresentable>(
    decoder: Decoder,
    keys: [K],
    context: String
) throws where K.RawValue == String {
    let rawContainer = try decoder.container(keyedBy: AnyNotebookCodingKey.self)
    let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
        .subtracting(keys.map(\.rawValue))
    guard unknownKeys.isEmpty else {
        throw DecodingError.dataCorrupted(
            .init(
                codingPath: decoder.codingPath,
                debugDescription: "\(context) contains unknown keys \(unknownKeys.sorted())"
            )
        )
    }
}

enum NotebookFixtureID: String, CaseIterable {
    case cardGallery
    case coverGallery
    case editGallery
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
        try rejectUnknownNotebookKeys(
            decoder: decoder,
            keys: CodingKeys.allCases,
            context: "UI World notebook entry"
        )
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
        try rejectUnknownNotebookKeys(
            decoder: decoder,
            keys: CodingKeys.allCases,
            context: "UI World notebook row"
        )
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

    enum CodingKeys: String, CodingKey, CaseIterable {
        case cardCount
        case dueCount
        case unlearnedCount
        case reviewedCount
        case pendingCount
        case lastActivity
        case isActive
    }

    init(from decoder: Decoder) throws {
        try rejectUnknownNotebookKeys(
            decoder: decoder,
            keys: CodingKeys.allCases,
            context: "UI World notebook cardState"
        )
        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                DecodingError.Context(
                    codingPath: container.codingPath,
                    debugDescription: "UI World notebook cardState must explicitly declare \(key.rawValue), even when null"
                )
            )
        }
        cardCount = try container.decode(Int.self, forKey: .cardCount)
        dueCount = try container.decode(Int.self, forKey: .dueCount)
        unlearnedCount = try container.decode(Int.self, forKey: .unlearnedCount)
        reviewedCount = try container.decode(Int.self, forKey: .reviewedCount)
        pendingCount = try container.decode(Int.self, forKey: .pendingCount)
        lastActivity = try container.decodeIfPresent(Date.self, forKey: .lastActivity)
        isActive = try container.decode(Bool.self, forKey: .isActive)
    }
}

struct NotebookEditStateSeed: Codable {
    let id: String
    let mode: String
    let name: String
    let color: String?
    let coverPattern: String?
    let coverImageAssetRef: String?

    enum CodingKeys: String, CodingKey, CaseIterable {
        case id
        case mode
        case name
        case color
        case coverPattern
        case coverImageAssetRef
    }

    init(from decoder: Decoder) throws {
        try rejectUnknownNotebookKeys(
            decoder: decoder,
            keys: CodingKeys.allCases,
            context: "UI World notebook edit state"
        )
        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                DecodingError.Context(
                    codingPath: container.codingPath,
                    debugDescription: "UI World notebook edit state must explicitly declare \(key.rawValue)"
                )
            )
        }
        id = try container.decode(String.self, forKey: .id)
        mode = try container.decode(String.self, forKey: .mode)
        name = try container.decode(String.self, forKey: .name)
        color = try container.decodeIfPresent(String.self, forKey: .color)
        coverPattern = try container.decodeIfPresent(String.self, forKey: .coverPattern)
        coverImageAssetRef = try container.decodeIfPresent(String.self, forKey: .coverImageAssetRef)
    }
}

struct NotebookFixtureSeed: Codable {
    let notebooks: [NotebookSeed]
    let editStates: [NotebookEditStateSeed]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case notebooks
        case editStates
    }

    init(from decoder: Decoder) throws {
        try rejectUnknownNotebookKeys(
            decoder: decoder,
            keys: CodingKeys.allCases,
            context: "UI World notebook fixture"
        )
        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                DecodingError.Context(
                    codingPath: container.codingPath,
                    debugDescription: "UI World notebook fixture must explicitly declare \(key.rawValue)"
                )
            )
        }
        notebooks = try container.decode([NotebookSeed].self, forKey: .notebooks)
        editStates = try container.decode([NotebookEditStateSeed].self, forKey: .editStates)
    }
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
        case .cardGallery, .coverGallery, .editGallery:
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
        case .editGallery:
            return ["edit"]
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
    static func editSheetMode(id: String, for fixtureID: NotebookFixtureID) -> NotebookEditSheet.Mode {
        let seed = FixtureDatasetStore.requireNotebookSeed(for: fixtureID)
        guard let state = seed.editStates.first(where: { $0.id == id }) else {
            preconditionFailure("UI World notebook.\(fixtureID.rawValue) is missing edit state \(id)")
        }
        if let pattern = state.coverPattern {
            precondition(
                NotebookCoverPattern(rawValue: pattern) != nil,
                "UI World notebook.\(fixtureID.rawValue).editStates.\(id) has unknown coverPattern \(pattern)"
            )
        }
        let coverImagePath: String?
        if let ref = state.coverImageAssetRef {
            do {
                let installedURL = try FixtureDatasetStore.requireInstalledAssetURL(ref: ref)
                coverImagePath = installedURL.path
            } catch {
                preconditionFailure("Failed to install UI World notebook.\(fixtureID.rawValue).editStates.\(id) asset \(ref): \(error)")
            }
        } else {
            coverImagePath = nil
        }
        switch state.mode {
        case "create":
            precondition(
                state.name.isEmpty && state.color == nil && state.coverPattern == nil && state.coverImageAssetRef == nil,
                "UI World notebook.\(fixtureID.rawValue).editStates.\(id) create mode must not carry edit appearance"
            )
            return .create
        case "edit":
            return .edit(
                name: state.name,
                color: state.color,
                coverPattern: state.coverPattern,
                coverImagePath: coverImagePath
            )
        default:
            preconditionFailure("UI World notebook.\(fixtureID.rawValue).editStates.\(id) has unknown mode \(state.mode)")
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
