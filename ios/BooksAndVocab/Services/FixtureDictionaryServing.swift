import Foundation

/// Deterministic retry gate used by unit/UI fixtures. The app exposes release
/// only behind an explicit UI-test launch argument; production fixture calls
/// keep the normal immediate retry behavior.
actor DictionaryRetryGate {
    static let shared = DictionaryRetryGate()

    private var continuation: CheckedContinuation<Void, Never>?
    private var activeWaitID: UUID?
    private var cancelledWaitIDs: Set<UUID> = []
    private var waiting = false

    func waitForRelease() async {
        let waitID = UUID()
        await withTaskCancellationHandler(operation: {
            await install(waitID: waitID)
        }, onCancel: {
            Task { await self.cancel(waitID: waitID) }
        })
    }

    func release() {
        guard let continuation else { return }
        self.continuation = nil
        activeWaitID = nil
        waiting = false
        continuation.resume()
    }

    func isWaiting() -> Bool {
        waiting
    }

    private func install(waitID: UUID) async {
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            if Task.isCancelled || cancelledWaitIDs.remove(waitID) != nil {
                continuation.resume()
                return
            }
            self.continuation = continuation
            activeWaitID = waitID
            waiting = true
        }
        if activeWaitID == waitID {
            activeWaitID = nil
            continuation = nil
            waiting = false
        }
    }

    private func cancel(waitID: UUID) {
        guard activeWaitID == waitID else {
            cancelledWaitIDs.insert(waitID)
            return
        }
        let continuation = self.continuation
        self.continuation = nil
        activeWaitID = nil
        waiting = false
        continuation?.resume()
    }
}

/// Canonical dictionary adapter for UI World runs.
///
/// The adapter is deliberately backed by `scenarioContext.dictionary`; it
/// does not carry a second response fixture or synthetic lexical source. Query
/// labels select the already-declared lookup states so UI tests can observe the
/// same loading/partial/offline/retry/error contract as the live presenter.
actor FixtureDictionaryServing: DictionaryServing {
    enum FixtureError: Error, Equatable {
        case unavailable(fixtureID: String)
        case unknownQuery(query: String)
        case missingCanonicalDictionary
        case invalidDataset(String)
    }

    private let dictionary: UIWorldDictionarySeed
    private let entry: LexicalEntry
    private let hit: DictionarySearchHit
    private let materialization: DictionaryMaterializationSnapshot
    private let retryGate: DictionaryRetryGate?
    private var attempts: [String: Int] = [:]
    private var pendingDetailFailures: [String: Int] = [:]
    private var pendingDetailFailureQuery: String?
    private var activeQuery: String?
    private(set) var materializationRequests: [DictionaryMaterializeLinkRequest] = []

    init(
        dictionary: UIWorldDictionarySeed,
        materialization: DictionaryMaterializationSnapshot,
        retryGate: DictionaryRetryGate?
    ) throws {
        self.dictionary = dictionary
        self.materialization = materialization
        self.retryGate = retryGate
        let attribution = LexicalAttribution(
            provider: dictionary.provenance.provider,
            sourceURL: "",
            licenseName: dictionary.provenance.sourceLabel,
            licenseURL: "",
            attributionText: dictionary.provenance.sourceLabel
        )
        var exampleByID: [String: UIWorldDictionaryExampleSeed] = [:]
        for example in dictionary.examples {
            guard exampleByID.updateValue(example, forKey: example.id) == nil else {
                throw FixtureError.invalidDataset(
                    "dictionary example IDs must be unique: \(example.id)"
                )
            }
        }
        var senses: [LexicalSense] = []
        for sense in dictionary.senses {
            var examples: [LexicalExample] = []
            for exampleID in sense.exampleIDs {
                guard let example = exampleByID[exampleID] else {
                    throw FixtureError.invalidDataset(
                        "dictionary sense \(sense.id) references missing example \(exampleID)"
                    )
                }
                guard example.senseID == sense.id else {
                    throw FixtureError.invalidDataset(
                        "dictionary example \(exampleID) belongs to \(example.senseID), not \(sense.id)"
                    )
                }
                examples.append(LexicalExample(id: example.id, text: example.text))
            }
            senses.append(
                LexicalSense(
                    id: sense.id,
                    partOfSpeech: sense.partOfSpeech,
                    definition: sense.gloss,
                    examples: examples
                )
            )
        }
        self.entry = LexicalEntry(
            provider: dictionary.provenance.provider,
            dictionaryId: dictionary.provenance.provider,
            entryKey: dictionary.provenance.entryID,
            schemaVersion: "1",
            word: dictionary.provenance.entryID,
            sourceLanguage: "en",
            targetLanguage: "zh-Hant",
            pronunciations: [],
            senses: senses,
            forms: [],
            sourceUrl: "",
            licenseName: dictionary.provenance.sourceLabel,
            licenseUrl: "",
            attributionText: dictionary.provenance.sourceLabel,
            fetchedAt: "fixture",
            truncated: false
        )
        self.hit = DictionarySearchHit(
            provider: dictionary.provenance.provider,
            dictionaryId: dictionary.provenance.provider,
            entryKey: dictionary.provenance.entryID,
            word: dictionary.provenance.entryID,
            language: "en",
            partsOfSpeech: dictionary.senses.map(\.partOfSpeech),
            hasExamples: !dictionary.examples.isEmpty,
            attribution: attribution
        )
    }

    static func fromFixtureDatasetStore(
        fixtureID: UIWorldDictionaryFixtureID = .p1DictionaryRich,
        retryGate: DictionaryRetryGate? = AppRuntimeOptions.shouldGateDictionaryRetry()
            ? DictionaryRetryGate.shared
            : nil
    ) throws -> FixtureDictionaryServing {
        guard let dictionary = FixtureDatasetStore.dictionarySeed(for: fixtureID) else {
            throw FixtureError.missingCanonicalDictionary
        }
        let materialization: DictionaryMaterializationSnapshot
        do {
            materialization = try FixtureDatasetStore.dictionaryRuntimeMaterialization(for: fixtureID)
        } catch {
            throw FixtureError.invalidDataset(String(describing: error))
        }
        return try FixtureDictionaryServing(
            dictionary: dictionary,
            materialization: materialization,
            retryGate: retryGate
        )
    }

    func searchDictionary(
        query: String,
        sourceLanguage: String,
        targetLanguage: String
    ) async throws -> DictionarySearchResponse {
        let queryKey = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let state = try state(for: queryKey)
        activeQuery = queryKey
        if pendingDetailFailureQuery != nil, pendingDetailFailureQuery != queryKey {
            pendingDetailFailures.removeAll()
            pendingDetailFailureQuery = nil
        }
        attempts[queryKey, default: 0] += 1
        guard let stateSeed = dictionary.lookup[state.rawValue] else {
            throw FixtureError.missingCanonicalDictionary
        }
        var shouldFailDetail = false

        switch state {
        case .idle:
            return response(hits: [])
        case .loading:
            // Keep the canonical loading fixture observable through the UI
            // harness's submit/event and first accessibility snapshot costs.
            try await Task.sleep(for: .milliseconds(250))
        case .result:
            if query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == "empty" {
                return response(hits: [])
            }
        case .partial:
            shouldFailDetail = attempts[queryKey] == 1
            break
        case .offline:
            throw KGError.offline
        case .error:
            throw FixtureError.unavailable(fixtureID: stateSeed.fixtureID)
        case .retry:
            if attempts[queryKey] == 1 {
                throw KGError.offline
            }
        }
        if let retryGate,
           attempts[queryKey, default: 0] > 1,
           state.rawValue == UIWorldDictionaryLookupState.partial.rawValue
                || state.rawValue == UIWorldDictionaryLookupState.retry.rawValue {
            await retryGate.waitForRelease()
        }
        try Task.checkCancellation()
        if shouldFailDetail {
            pendingDetailFailures[entry.entryKey, default: 0] += 1
            pendingDetailFailureQuery = queryKey
        }
        return response(hits: [hit])
    }

    func fetchDictionaryEntry(
        provider: String,
        entryKey: String,
        targetLanguage: String
    ) async throws -> DictionaryEntryResponse {
        if pendingDetailFailures[entryKey, default: 0] > 0 {
            pendingDetailFailures[entryKey, default: 0] -= 1
            throw KGError.offline
        }
        let responseEntry: LexicalEntry
        if activeQuery == "missing-example" {
            responseEntry = LexicalEntry(
                provider: entry.provider,
                dictionaryId: entry.dictionaryId,
                entryKey: entry.entryKey,
                schemaVersion: entry.schemaVersion,
                word: entry.word,
                sourceLanguage: entry.sourceLanguage,
                targetLanguage: entry.targetLanguage,
                pronunciations: entry.pronunciations,
                senses: entry.senses.map { sense in
                    sense.id == "sense-2"
                        ? LexicalSense(
                            id: sense.id,
                            partOfSpeech: sense.partOfSpeech,
                            definition: sense.definition,
                            examples: []
                        )
                        : sense
                },
                forms: entry.forms,
                sourceUrl: entry.sourceUrl,
                licenseName: entry.licenseName,
                licenseUrl: entry.licenseUrl,
                attributionText: entry.attributionText,
                fetchedAt: entry.fetchedAt,
                truncated: entry.truncated
            )
        } else {
            responseEntry = entry
        }
        return DictionaryEntryResponse(
            entry: responseEntry,
            cacheStatus: "fixture",
            materialization: materialization
        )
    }

    func materializeDictionaryLink(
        request: DictionaryMaterializeLinkRequest,
        idempotencyKey: String
    ) async throws -> DictionaryMaterializeLinkResponse {
        materializationRequests.append(request)
        if activeQuery == "materialize-error" {
            throw FixtureError.unavailable(fixtureID: "dictionary.p2.materialize-error")
        }
        guard request.provider == entry.provider,
              request.entryKey == entry.entryKey,
              let sense = entry.senses.first(where: { $0.id == request.senseKey }),
              sense.examples.contains(where: { $0.id == request.exampleKey }) else {
            throw FixtureError.missingCanonicalDictionary
        }

        guard let example = sense.examples.first(where: { $0.id == request.exampleKey }) else {
            throw FixtureError.missingCanonicalDictionary
        }
        let targetCardID = "fixture-dictionary-card"
        let link = KGGraphLink(
            id: "fixture-dictionary-link",
            fromId: request.sourceCardId,
            toId: targetCardID,
            kind: "shares_usage",
            confidence: 0.91,
            reason: "canonical dictionary fixture materialization"
        )
        let targetCard: KGCard = try decodeJSON([
            "id": targetCardID,
            "content": entry.word,
            "meaning": sense.definition,
            "pos": sense.partOfSpeech ?? "",
            "note": entry.attributionText,
            "examples": [example.text],
            "mode": "recognition",
            "isDeleted": false,
            "isArchived": false,
            "notebookId": request.notebookId,
            "cardRole": "dictionary",
            "reviewEligible": false,
            "readerHidden": false,
            "promotionState": "idle",
            "linksByKind": [String: Any]()
        ])
        let projection: KGDictionaryCardProjection = try decodeJSON([
            "card": [
                "id": targetCardID,
                "content": entry.word,
                "meaning": sense.definition,
                "pos": sense.partOfSpeech ?? "",
                "note": entry.attributionText,
                "examples": [example.text],
                "mode": "recognition",
                "isDeleted": false,
                "isArchived": false,
                "notebookId": request.notebookId,
                "cardRole": "dictionary",
                "reviewEligible": false,
                "readerHidden": false,
                "promotionState": "idle",
                "linksByKind": [String: Any](),
            ],
            "dictionary": [
                "card": [
                    "id": targetCardID,
                    "content": entry.word,
                    "meaning": sense.definition,
                    "pos": sense.partOfSpeech ?? "",
                    "note": entry.attributionText,
                    "examples": [example.text],
                    "mode": "recognition",
                    "isDeleted": false,
                    "isArchived": false,
                    "notebookId": request.notebookId,
                    "cardRole": "dictionary",
                    "reviewEligible": false,
                    "readerHidden": false,
                    "promotionState": "idle",
                    "linksByKind": [String: Any](),
                ],
                "entry": try encodedDictionaryEntry(),
                "selectedSenseKey": request.senseKey,
                "selectedExampleKey": request.exampleKey,
                "materializationStatus": "succeeded",
                "promotionErrorCode": NSNull(),
                "promotionRetryable": false,
            ],
            "readerHidden": false,
            "links": [try encodedGraphLink(link)]
        ])
        return DictionaryMaterializeLinkResponse(
            targetCard: targetCard,
            dictionaryCard: projection,
            link: link,
            createdCard: true,
            createdLink: true,
            replayed: !idempotencyKey.isEmpty && materializationRequests.count > 1
        )
    }

    private func encodedDictionaryEntry() throws -> Any {
        try JSONSerialization.jsonObject(with: JSONEncoder().encode(entry))
    }

    private func encodedGraphLink(_ link: KGGraphLink) throws -> Any {
        try JSONSerialization.jsonObject(with: JSONEncoder().encode(link))
    }

    private func decodeJSON<T: Decodable>(_ object: Any) throws -> T {
        try JSONDecoder().decode(T.self, from: JSONSerialization.data(withJSONObject: object))
    }

    private func state(for query: String) throws -> UIWorldDictionaryLookupState {
        let normalized = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if normalized == "missing-example" || normalized == "materialize-error" {
            guard dictionary.lookup[UIWorldDictionaryLookupState.result.rawValue] != nil else {
                throw FixtureError.missingCanonicalDictionary
            }
            return .result
        }
        // `empty` is an explicit legacy fixture selector for an empty result;
        // it is not a lookup state and therefore must not be generalized into
        // a fallback for arbitrary typos.
        if normalized == "empty" {
            guard dictionary.lookup[UIWorldDictionaryLookupState.result.rawValue] != nil else {
                throw FixtureError.missingCanonicalDictionary
            }
            return .result
        }
        if normalized == entry.word.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
            guard dictionary.lookup[UIWorldDictionaryLookupState.result.rawValue] != nil else {
                throw FixtureError.missingCanonicalDictionary
            }
            return .result
        }
        guard let state = UIWorldDictionaryLookupState(rawValue: normalized),
              dictionary.lookup[normalized] != nil else {
            throw FixtureError.unknownQuery(query: normalized)
        }
        return state
    }

    private func response(hits: [DictionarySearchHit]) -> DictionarySearchResponse {
        DictionarySearchResponse(hits: hits, cacheStatus: "fixture")
    }
}
