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

enum DictionaryMaterializePhase: Equatable {
    case idle
    case running
    case succeeded
    case failed
}

@Observable @MainActor
final class AddLinkCoordinator {
    private(set) var searchPhase: DictionarySearchPhase = .idle
    private(set) var materializePhase: DictionaryMaterializePhase = .idle
    private(set) var selectedSenseKey: String?
    private(set) var selectedExampleKey: String?

    private var searchGeneration = 0
    private var searchTask: Task<Void, Never>?
    private var materializeKey: String?
    private var materializeRequest: DictionaryMaterializeLinkRequest?

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
            searchPhase = .idle
            return
        }

        searchTask?.cancel()
        searchGeneration += 1
        let generation = searchGeneration
        searchPhase = .loading
        clearSelection()

        searchTask = Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                let search = try await service.searchDictionary(
                    query: trimmed,
                    sourceLanguage: sourceLanguage,
                    targetLanguage: targetLanguage
                )
                try Task.checkCancellation()
                guard generation == searchGeneration else { return }
                guard let hit = search.hits.first else {
                    searchPhase = .empty
                    return
                }
                let detail = try await service.fetchDictionaryEntry(
                    provider: hit.provider,
                    entryKey: hit.entryKey,
                    targetLanguage: targetLanguage
                )
                try Task.checkCancellation()
                guard generation == searchGeneration else { return }
                searchPhase = .result(detail.entry, cacheStatus: detail.cacheStatus)
            } catch is CancellationError {
                // A newer submit owns the UI state.
            } catch {
                guard generation == searchGeneration else { return }
                searchPhase = .failed(Self.classify(error))
            }
        }
    }

    func cancelSearch() {
        searchTask?.cancel()
        searchTask = nil
        searchGeneration += 1
        if searchPhase == .loading { searchPhase = .idle }
    }

    func queryDidChange() {
        cancelSearch()
        searchPhase = .idle
        clearSelection()
    }

    func select(senseKey: String, exampleKey: String) {
        selectedSenseKey = senseKey
        selectedExampleKey = exampleKey
        materializePhase = .idle
        materializeKey = nil
        materializeRequest = nil
    }

    func materializeSelectedExample(
        sourceEntry: VocabularyEntry,
        entry: LexicalEntry,
        using service: any DictionaryServing,
        container: ModelContainer
    ) async {
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
        do {
            let response = try await service.materializeDictionaryLink(
                request: request,
                idempotencyKey: materializeKey
            )
            let actor = BackgroundSyncActor(modelContainer: container)
            _ = try await actor.upsertDictionaryMaterialization(response)
            if response.dictionaryCard == nil,
               let saved = try? await service.fetchDictionaryCard(cardId: response.targetCard.id) {
                _ = try? await actor.upsertDictionaryProjection(saved)
            }
            Self.applyMaterializedLink(response, to: sourceEntry)
            materializePhase = .succeeded
            self.materializeKey = nil
            materializeRequest = nil
        } catch is CancellationError {
            materializePhase = .idle
        } catch {
            // Keep the idempotency key so explicit Retry converges the saga.
            materializePhase = .failed
        }
    }

    func linkExisting(
        target: VocabularyEntry,
        sourceEntry: VocabularyEntry,
        using service: any KGServing
    ) async {
        guard let sourceCardID = sourceEntry.kgCardId,
              let pending = VocabularyGraphLinkMutation.beginManualLink(
                from: sourceEntry, to: target
              ) else { return }
        materializePhase = .running
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
        }
    }

    private func clearSelection() {
        selectedSenseKey = nil
        selectedExampleKey = nil
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
}
