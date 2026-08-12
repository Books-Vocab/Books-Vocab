import Foundation

/// Canonical dictionary adapter for UI World runs.
///
/// The adapter is deliberately backed by `scenarioContext.dictionary`; it
/// does not carry a second response fixture or synthetic lexical source. Query
/// labels select the already-declared lookup states so UI tests can observe the
/// same loading/partial/offline/retry/error contract as the live presenter.
actor FixtureDictionaryServing: DictionaryServing {
    enum FixtureError: Error, Equatable {
        case unavailable(fixtureID: String)
        case missingCanonicalDictionary
        case invalidDataset(String)
    }

    private let dictionary: UIWorldDictionarySeed
    private let entry: LexicalEntry
    private let hit: DictionarySearchHit
    private let materialization: DictionaryMaterializationSnapshot
    private var attempts: [String: Int] = [:]
    private var pendingDetailFailures: [String: Int] = [:]
    private var pendingDetailFailureQuery: String?
    private(set) var materializationRequests: [DictionaryMaterializeLinkRequest] = []

    init(dictionary: UIWorldDictionarySeed) {
        self.dictionary = dictionary
        let attribution = LexicalAttribution(
            provider: dictionary.provenance.provider,
            sourceURL: "",
            licenseName: dictionary.provenance.sourceLabel,
            licenseURL: "",
            attributionText: dictionary.provenance.sourceLabel
        )
        let exampleByID = Dictionary(uniqueKeysWithValues: dictionary.examples.map { ($0.id, $0) })
        let senses = dictionary.senses.map { sense in
            LexicalSense(
                id: sense.id,
                partOfSpeech: sense.partOfSpeech,
                definition: sense.gloss,
                examples: sense.exampleIDs.compactMap { exampleID in
                    guard let example = exampleByID[exampleID] else { return nil }
                    return LexicalExample(id: example.id, text: example.text)
                }
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
        self.materialization = FixtureDatasetStore.dictionaryRuntimeMaterialization(
            for: .p1DictionaryRich
        ) ?? DictionaryMaterializationSnapshot(
            status: dictionary.materialization.status,
            selectedSenseID: dictionary.materialization.selectedSenseID,
            selectedExampleID: dictionary.materialization.selectedExampleID,
            sourceFixtureID: dictionary.materialization.sourceFixtureID
        )
    }

    static func fromFixtureDatasetStore(
        fixtureID: UIWorldDictionaryFixtureID = .p1DictionaryRich
    ) throws -> FixtureDictionaryServing {
        guard let dictionary = FixtureDatasetStore.dictionarySeed(for: fixtureID) else {
            throw FixtureError.missingCanonicalDictionary
        }
        return FixtureDictionaryServing(dictionary: dictionary)
    }

    func searchDictionary(
        query: String,
        sourceLanguage: String,
        targetLanguage: String
    ) async throws -> DictionarySearchResponse {
        let state = state(for: query)
        let queryKey = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
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
            if attempts[state.rawValue] == 1 {
                throw KGError.offline
            }
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
        return DictionaryEntryResponse(
            entry: entry,
            cacheStatus: "fixture",
            materialization: materialization
        )
    }

    func materializeDictionaryLink(
        request: DictionaryMaterializeLinkRequest,
        idempotencyKey: String
    ) async throws -> DictionaryMaterializeLinkResponse {
        materializationRequests.append(request)
        guard request.provider == entry.provider,
              request.entryKey == entry.entryKey,
              let sense = entry.senses.first(where: { $0.id == request.senseKey }),
              sense.examples.contains(where: { $0.id == request.exampleKey }) else {
            throw FixtureError.missingCanonicalDictionary
        }

        let example = sense.examples.first(where: { $0.id == request.exampleKey })!
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
                "promotionState": "idle",
                "linksByKind": [String: Any](),
            ],
            "dictionaryEntry": try encodedDictionaryEntry(),
            "selectedSenseKey": request.senseKey,
            "selectedExampleKey": request.exampleKey,
            "materializationStatus": "succeeded",
            "promotionErrorCode": NSNull(),
            "promotionRetryable": false,
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

    private func state(for query: String) -> UIWorldDictionaryLookupState {
        let normalized = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard let state = UIWorldDictionaryLookupState(rawValue: normalized), dictionary.lookup[normalized] != nil else {
            return .result
        }
        return state
    }

    private func response(hits: [DictionarySearchHit]) -> DictionarySearchResponse {
        DictionarySearchResponse(hits: hits, cacheStatus: "fixture")
    }
}
