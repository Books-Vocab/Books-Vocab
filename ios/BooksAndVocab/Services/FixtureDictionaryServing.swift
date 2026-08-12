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
    }

    private enum LookupState: String {
        case idle
        case loading
        case result
        case partial
        case offline
        case error
        case retry
    }

    private let dictionary: UIWorldDictionarySeed
    private let entry: LexicalEntry
    private let hit: DictionarySearchHit
    private let materialization: DictionaryMaterializationSnapshot
    private var attempts: [String: Int] = [:]
    private var lastState: LookupState = .idle

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
        self.materialization = DictionaryMaterializationSnapshot(
            status: dictionary.materialization.status,
            selectedSenseID: dictionary.materialization.selectedSenseID,
            selectedExampleID: dictionary.materialization.selectedExampleID,
            sourceFixtureID: dictionary.materialization.sourceFixtureID
        )
    }

    static func fromFixtureDatasetStore() throws -> FixtureDictionaryServing {
        guard let dictionary = FixtureDatasetStore.scenarioContext()?.dictionary else {
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
        lastState = state
        attempts[state.rawValue, default: 0] += 1
        guard let stateSeed = dictionary.lookup[state.rawValue] else {
            throw FixtureError.missingCanonicalDictionary
        }

        switch state {
        case .idle:
            return response(hits: [])
        case .loading:
            // Keep the canonical loading fixture observable through the UI
            // harness's submit/event and first accessibility snapshot costs.
            try await Task.sleep(for: .seconds(2))
        case .result:
            if query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == "empty" {
                return response(hits: [])
            }
        case .partial:
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
        return response(hits: [hit])
    }

    func fetchDictionaryEntry(
        provider: String,
        entryKey: String,
        targetLanguage: String
    ) async throws -> DictionaryEntryResponse {
        if lastState == .partial, attempts[LookupState.partial.rawValue] == 1 {
            throw KGError.offline
        }
        if lastState == .offline || lastState == .error {
            throw KGError.offline
        }
        return DictionaryEntryResponse(
            entry: entry,
            cacheStatus: "fixture",
            materialization: materialization
        )
    }

    private func state(for query: String) -> LookupState {
        let normalized = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard let state = LookupState(rawValue: normalized), dictionary.lookup[normalized] != nil else {
            return .result
        }
        return state
    }

    private func response(hits: [DictionarySearchHit]) -> DictionarySearchResponse {
        DictionarySearchResponse(hits: hits, cacheStatus: "fixture")
    }
}
