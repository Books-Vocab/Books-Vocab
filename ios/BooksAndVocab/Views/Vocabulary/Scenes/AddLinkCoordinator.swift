import Foundation
import Observation
import SwiftData

enum DictionarySearchFailure: Equatable {
    case offline
    case rateLimited
    case timeout
    case malformed
    case unavailable
}

enum DictionarySearchPhase: Equatable {
    case idle
    case loading
    case empty
    case result(LexicalEntry, cacheStatus: String)
    case failed(DictionarySearchFailure)
}

enum DictionaryLookupState: Equatable {
    case idle
    case loading(query: String)
    case partial(query: String, hit: DictionarySearchHit, failure: DictionarySearchFailure)
    case success(query: String, entry: LexicalEntry?, cacheStatus: String)
    case error(query: String, failure: DictionarySearchFailure)
    case offline(query: String)
    case retry(query: String, attempt: Int)

    var isPartial: Bool {
        if case .partial = self { return true }
        return false
    }

    var isSuccess: Bool {
        if case .success = self { return true }
        return false
    }

    var isOffline: Bool {
        if case .offline = self { return true }
        return false
    }
}

struct DictionaryMaterializedSelection: Equatable {
    let sense: LexicalSense
    let example: LexicalExample
    let provenance: LexicalAttribution
}

enum DictionarySelectionState: Equatable {
    case unavailable
    case selected(DictionaryMaterializedSelection)
    case invalid(senseKey: String, exampleKey: String)
}

extension DictionarySelectionState {
    var isSelected: Bool {
        if case .selected = self { return true }
        return false
    }

    var materialization: DictionaryMaterializedSelection? {
        if case .selected(let value) = self { return value }
        return nil
    }
}

enum DictionaryMaterializeFailure: Equatable {
    case offline
    case rateLimited
    case timeout
    case malformed
    case unavailable
}

enum DictionaryMaterializePhase: Equatable {
    case idle
    case running
    case succeeded
    case failed
}

private enum DictionaryMaterializationError: Error {
    case projectionCardMismatch(expected: String, actual: String)
    case projectionMissingGraphLink(linkID: String)
    case projectionGraphLinkMismatch(linkID: String)
    case projectionGraphLinkEndpointsMismatch(linkID: String)
    case projectionGraphLinkKindMismatch(linkID: String)
}

@Observable @MainActor
final class AddLinkCoordinator {
    private(set) var lookupState: DictionaryLookupState = .idle
    private(set) var materializePhase: DictionaryMaterializePhase = .idle
    private(set) var materializeFailure: DictionaryMaterializeFailure?
    private(set) var selectionState: DictionarySelectionState = .unavailable
    private(set) var selectedSenseKey: String?
    private(set) var selectedExampleKey: String?
    private(set) var dictionaryMaterialization: DictionaryMaterializationSnapshot?

    private var searchGeneration = 0
    private var searchTask: Task<Void, Never>?
    private var materializeKey: String?
    private var materializeRequest: DictionaryMaterializeLinkRequest?
    private var lastQuery: String?
    private var retryAttempt = 0
    private var lastHit: DictionarySearchHit?
    private var lastEntry: LexicalEntry?
    private var lastCacheStatus = ""

    var selectedMaterialization: DictionaryMaterializedSelection? {
        selectionState.materialization
    }

    /// Compatibility projection for older callers. `lookupState` is the only
    /// authoritative lookup state; this value is derived and cannot drift.
    var searchPhase: DictionarySearchPhase {
        switch lookupState {
        case .idle:
            return .idle
        case .loading, .retry:
            return .loading
        case .success(_, let entry, let cacheStatus):
            guard let entry else { return .empty }
            return .result(entry, cacheStatus: cacheStatus)
        case .partial(_, _, let failure), .error(_, let failure):
            return .failed(failure)
        case .offline:
            return .failed(.offline)
        }
    }

    func lookupFailure(for state: DictionaryLookupState) -> DictionarySearchFailure {
        switch state {
        case .partial(_, _, let failure), .error(_, let failure): return failure
        case .offline: return .offline
        case .idle, .loading, .success, .retry: return .unavailable
        }
    }

    nonisolated static func localCandidates(
        query: String,
        sourceEntry: VocabularyEntry,
        allEntries: [VocabularyEntry]
    ) -> [VocabularyEntry] {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return [] }
        let linkedIDs = Set(sourceEntry.graphLinksByKind.values.flatMap { $0 }.map(\.cardId))
        let folded = trimmed.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: .current)
        return Array(allEntries.lazy.filter { entry in
            entry.id != sourceEntry.id
                && entry.notebookId == sourceEntry.notebookId
                && entry.kgCardId != nil
                && !entry.isArchived
                && !(entry.kgCardId.map(linkedIDs.contains) ?? false)
                && (entry.word.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: .current).contains(folded)
                    || entry.translation.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: .current).contains(folded))
        }.prefix(20))
    }

    nonisolated static func existingEntry(
        for word: String,
        notebookID: String,
        excluding sourceID: UUID? = nil,
        allEntries: [VocabularyEntry]
    ) -> VocabularyEntry? {
        let normalized = normalize(word)
        return allEntries.first {
            $0.id != sourceID
                && $0.notebookId == notebookID
                && $0.syncAction != .delete
                && normalize($0.word) == normalized
        }
    }

    func submitSearch(
        query: String,
        using service: any DictionaryServing,
        sourceLanguage: String = "en",
        targetLanguage: String = "zh-Hant"
    ) {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            cancelSearch()
            lookupState = .idle
            return
        }

        retryAttempt = 0
        startSearch(
            query: trimmed,
            using: service,
            sourceLanguage: sourceLanguage,
            targetLanguage: targetLanguage,
            state: .loading(query: trimmed)
        )
    }

    func retrySearch(
        using service: any DictionaryServing,
        sourceLanguage: String = "en",
        targetLanguage: String = "zh-Hant"
    ) {
        guard let lastQuery else { return }
        retryAttempt += 1
        startSearch(
            query: lastQuery,
            using: service,
            sourceLanguage: sourceLanguage,
            targetLanguage: targetLanguage,
            state: .retry(query: lastQuery, attempt: retryAttempt)
        )
    }

    private func startSearch(
        query: String,
        using service: any DictionaryServing,
        sourceLanguage: String,
        targetLanguage: String,
        state: DictionaryLookupState
    ) {
        searchTask?.cancel()
        searchGeneration += 1
        let generation = searchGeneration
        lastQuery = query
        lookupState = state
        clearSelection()
        PerfLog.dictionary.mark(
            "dictionary.lookup.started",
            "query=\(query) state=\(String(describing: state))"
        )

        searchTask = Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                let search = try await service.searchDictionary(
                    query: query,
                    sourceLanguage: sourceLanguage,
                    targetLanguage: targetLanguage
                )
                try Task.checkCancellation()
                guard generation == searchGeneration else { return }
                guard let hit = search.hits.first else {
                    self.lastHit = nil
                    self.lastEntry = nil
                    self.lastCacheStatus = search.cacheStatus
                    self.lookupState = .success(
                        query: query, entry: nil, cacheStatus: search.cacheStatus
                    )
                    return
                }
                self.lastHit = hit
                let detail = try await service.fetchDictionaryEntry(
                    provider: hit.provider,
                    entryKey: hit.entryKey,
                    targetLanguage: targetLanguage
                )
                try Task.checkCancellation()
                guard generation == searchGeneration else { return }
                self.lastEntry = detail.entry
                self.lastCacheStatus = detail.cacheStatus
                self.dictionaryMaterialization = detail.materialization
                self.lookupState = .success(
                    query: query, entry: detail.entry, cacheStatus: detail.cacheStatus
                )
                PerfLog.dictionary.mark(
                    "dictionary.lookup.succeeded",
                    Self.provenanceDetail(detail.materialization)
                )
                if let materialization = detail.materialization,
                   materialization.status == "ready",
                   let senseID = materialization.selectedSenseID,
                   let exampleID = materialization.selectedExampleID {
                    select(senseKey: senseID, exampleKey: exampleID)
                }
            } catch is CancellationError {
                // A newer submit owns the UI state.
            } catch {
                guard generation == searchGeneration else { return }
                let failure = Self.classify(error)
                if let hit = self.lastHit {
                    self.lookupState = .partial(
                        query: query, hit: hit, failure: failure
                    )
                } else if failure == .offline {
                    self.lookupState = .offline(query: query)
                } else {
                    self.lookupState = .error(query: query, failure: failure)
                }
                PerfLog.dictionary.mark(
                    "dictionary.lookup.failed",
                    "query=\(query) failure=\(String(describing: failure))"
                )
            }
        }
    }

    func cancelSearch() {
        searchTask?.cancel()
        searchTask = nil
        searchGeneration += 1
        switch lookupState {
        case .loading, .retry:
            lookupState = .idle
        default:
            break
        }
    }

    func queryDidChange() {
        cancelSearch()
        lookupState = .idle
        clearSelection()
    }

    func select(senseKey: String, exampleKey: String) {
        selectedSenseKey = senseKey
        selectedExampleKey = exampleKey
        guard let entry = lastEntry,
              let sense = entry.senses.first(where: { $0.id == senseKey }),
              let example = sense.examples.first(where: { $0.id == exampleKey }) else {
            selectionState = .invalid(senseKey: senseKey, exampleKey: exampleKey)
            return
        }
        selectionState = .selected(
            DictionaryMaterializedSelection(
                sense: sense,
                example: example,
                provenance: LexicalAttribution(
                    provider: entry.provider,
                    sourceURL: entry.sourceUrl,
                    licenseName: entry.licenseName,
                    licenseURL: entry.licenseUrl,
                    attributionText: entry.attributionText
                )
            )
        )
        materializePhase = .idle
        materializeFailure = nil
        materializeKey = nil
        materializeRequest = nil
    }

    func selectSense(senseKey: String) {
        guard let entry = lastEntry,
              entry.senses.contains(where: { $0.id == senseKey }) else {
            selectionState = .invalid(senseKey: senseKey, exampleKey: "")
            return
        }
        selectedSenseKey = senseKey
        selectedExampleKey = nil
        selectionState = .unavailable
        materializePhase = .idle
        materializeFailure = nil
        materializeKey = nil
        materializeRequest = nil
    }

    func materializeSelectedExample(
        sourceEntry: VocabularyEntry,
        entry: LexicalEntry,
        using service: any DictionaryServing,
        container: ModelContainer
    ) async {
        guard let sourceContext = sourceEntry.modelContext else {
            materializePhase = .failed
            materializeFailure = .malformed
            return
        }
        guard let sourceCardID = sourceEntry.kgCardId,
              let senseKey = selectedSenseKey,
              let exampleKey = selectedExampleKey else { return }

        let request = DictionaryMaterializeLinkRequest(
            sourceCardId: sourceCardID,
            notebookId: sourceEntry.notebookId,
            provider: entry.provider,
            entryKey: entry.entryKey,
            senseKey: senseKey,
            exampleKey: exampleKey
        )
        if materializeRequest != request || materializeKey == nil {
            materializeRequest = request
            materializeKey = UUID().uuidString
        }
        guard let materializeKey else { return }

        materializePhase = .running
        materializeFailure = nil
        PerfLog.dictionary.mark(
            "dictionary.materialization.started",
            Self.provenanceDetail(dictionaryMaterialization)
        )
        do {
            let response = try await service.materializeDictionaryLink(
                request: request,
                idempotencyKey: materializeKey
            )
            let projection: KGDictionaryCardProjection
            if let dictionaryCard = response.dictionaryCard {
                projection = dictionaryCard
            } else {
                projection = try await service.fetchDictionaryCard(cardId: response.targetCard.id)
            }
            guard projection.card.id == response.targetCard.id else {
                throw DictionaryMaterializationError.projectionCardMismatch(
                    expected: response.targetCard.id,
                    actual: projection.card.id
                )
            }
            let matchingLinks = projection.links.filter { $0.id == response.link.id }
            guard matchingLinks.count == 1 else {
                throw DictionaryMaterializationError.projectionMissingGraphLink(
                    linkID: response.link.id
                )
            }
            guard matchingLinks[0] == response.link else {
                throw DictionaryMaterializationError.projectionGraphLinkMismatch(
                    linkID: response.link.id
                )
            }
            guard response.link.fromId == request.sourceCardId,
                  response.link.toId == response.targetCard.id else {
                throw DictionaryMaterializationError.projectionGraphLinkEndpointsMismatch(
                    linkID: response.link.id
                )
            }
            guard response.link.kind == "shares_usage" else {
                throw DictionaryMaterializationError.projectionGraphLinkKindMismatch(
                    linkID: response.link.id
                )
            }
            let actor = BackgroundSyncActor(modelContainer: container)
            _ = try await actor.upsertDictionaryMaterialization(response)
            if response.dictionaryCard == nil {
                _ = try await actor.upsertDictionaryProjection(projection)
            }
            Self.applyMaterializedLink(response, to: sourceEntry)
            try sourceContext.save()
            materializePhase = .succeeded
            PerfLog.dictionary.mark(
                "dictionary.materialization.succeeded",
                Self.provenanceDetail(dictionaryMaterialization)
            )
            self.materializeKey = nil
            materializeRequest = nil
        } catch is CancellationError {
            materializePhase = .idle
        } catch let error as DictionaryMaterializationError {
            // A materialization without a read-back projection/link is not a
            // successful graph mutation, even when the POST itself succeeded.
            materializePhase = .failed
            materializeFailure = .malformed
            PerfLog.dictionary.mark(
                "dictionary.materialization.failed",
                "failure=\(String(describing: error)) \(Self.provenanceDetail(dictionaryMaterialization))"
            )
        } catch {
            // Keep the idempotency key so explicit Retry converges the saga.
            materializePhase = .failed
            materializeFailure = Self.classifyMaterialize(error)
            PerfLog.dictionary.mark(
                "dictionary.materialization.failed",
                "failure=\(String(describing: materializeFailure)) \(Self.provenanceDetail(dictionaryMaterialization))"
            )
        }
    }

    func linkExisting(
        target: VocabularyEntry,
        sourceEntry: VocabularyEntry,
        using service: any GraphServing
    ) async {
        guard sourceEntry.modelContext != nil else {
            materializePhase = .failed
            materializeFailure = .malformed
            return
        }
        guard let sourceCardID = sourceEntry.kgCardId,
              let pending = VocabularyGraphLinkMutation.beginManualLink(
                from: sourceEntry, to: target
              ) else { return }
        materializePhase = .running
        materializeFailure = nil
        do {
            let link = try await service.createManualLink(
                fromId: sourceCardID,
                toId: pending.targetCardId,
                notebookId: sourceEntry.notebookId
            )
            VocabularyGraphLinkMutation.commitManualLink(pending, result: link, on: sourceEntry)
            materializePhase = .succeeded
        } catch is CancellationError {
            VocabularyGraphLinkMutation.rollbackManualLink(pending, on: sourceEntry)
            materializePhase = .idle
        } catch {
            VocabularyGraphLinkMutation.rollbackManualLink(pending, on: sourceEntry)
            materializePhase = .failed
            materializeFailure = Self.classifyMaterialize(error)
        }
    }

    private func clearSelection() {
        selectedSenseKey = nil
        selectedExampleKey = nil
        dictionaryMaterialization = nil
        selectionState = .unavailable
        materializeFailure = nil
        lastHit = nil
        lastEntry = nil
        lastCacheStatus = ""
        materializePhase = .idle
        materializeKey = nil
        materializeRequest = nil
    }

    private static func applyMaterializedLink(
        _ response: DictionaryMaterializeLinkResponse,
        to sourceEntry: VocabularyEntry
    ) {
        let graph = response.link
        let target = response.targetCard
        let summary = KGCardLinkSummary(
            id: graph.id,
            cardId: target.id,
            word: target.content,
            kind: graph.kind,
            label: graph.kind,
            confidence: graph.confidence,
            reason: graph.reason,
            hidden: false
        )
        var links = sourceEntry.graphLinksByKind
        var group = links[graph.kind] ?? []
        if let index = group.firstIndex(where: { $0.id == graph.id || $0.cardId == target.id }) {
            group[index] = summary
        } else {
            group.append(summary)
        }
        links[graph.kind] = group
        sourceEntry.graphLinksByKind = links
    }

    private static func provenanceDetail(
        _ materialization: DictionaryMaterializationSnapshot?
    ) -> String {
        guard let materialization else { return "provenance=none" }
        return [
            "fixtureID=\(materialization.sourceFixtureID)",
            "datasetID=\(materialization.datasetID)",
            "datasetSHA256=\(materialization.datasetSHA256)",
            "sourceAssetID=\(materialization.sourceAssetID)",
            "sourceAssetPath=\(materialization.sourceAssetPath)",
            "sourceAssetByteSize=\(materialization.sourceAssetByteSize)",
            "sourceAssetSHA256=\(materialization.sourceAssetSHA256)",
        ].joined(separator: " ")
    }

    nonisolated private static func normalize(_ value: String) -> String {
        value.precomposedStringWithCanonicalMapping
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
    }

    private static func classify(_ error: Error) -> DictionarySearchFailure {
        if let urlError = error as? URLError {
            switch urlError.code {
            case .notConnectedToInternet, .networkConnectionLost: return .offline
            case .timedOut: return .timeout
            default: return .unavailable
            }
        }
        if let kgError = error as? KGError {
            switch kgError {
            case .offline: return .offline
            case .httpError(let statusCode, _):
                return statusCode == 429 ? .rateLimited : .unavailable
            case .decodingError: return .malformed
            case .networkError(let underlying):
                return classify(underlying)
            default: return .unavailable
            }
        }
        return .unavailable
    }

    private static func classifyMaterialize(_ error: Error) -> DictionaryMaterializeFailure {
        switch classify(error) {
        case .offline: return .offline
        case .rateLimited: return .rateLimited
        case .timeout: return .timeout
        case .malformed: return .malformed
        case .unavailable: return .unavailable
        }
    }
}
