import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@Suite("Dictionary card V1 domain")
struct DictionaryCardV1Tests {
    private func entry(
        _ word: String,
        role: VocabularyCardRole = .learning,
        eligible: Bool = true,
        added: Date = .now
    ) -> VocabularyEntry {
        let value = VocabularyEntry(
            word: word,
            translation: "meaning",
            context: "context",
            bookTitle: "Book"
        )
        value.cardRole = role
        value.reviewEligible = eligible
        value.dateAdded = added
        value.markSynced()
        return value
    }

    @Test("new entries remain learning cards")
    func legacyDefaults() {
        let value = entry("legacy")

        #expect(value.cardRole == .learning)
        #expect(value.reviewEligible)
        #expect(value.promotionState == .idle)
    }

    @Test("dictionary role and reader visibility are independent")
    func dictionaryReaderEligibility() {
        let value = entry("lexeme", role: .dictionary, eligible: false)

        #expect(value.shouldAppearInReader)
        #expect(!value.shouldAppearInReview)
        value.isExcludedFromReader = true
        #expect(!value.shouldAppearInReader)
    }

    @Test("review classification excludes dictionary cards")
    func reviewClassification() {
        let learning = entry("learn")
        let dictionary = entry("reference", role: .dictionary, eligible: false)

        let result = VocabularyEntryPresentation.classifyKnowledgeEntries(
            in: [dictionary, learning],
            now: .now.addingTimeInterval(60 * 60 * 24)
        )

        #expect(result.dueCount + result.unlearnedCount + result.reviewedCount == 1)
        #expect(result.mergedBucket(for: []).map(\.word) == ["learn"])
    }

    @MainActor
    @Test("today review fallback excludes dictionary cards")
    func todayReviewFallback() {
        let learning = entry("learn")
        let dictionary = entry("reference", role: .dictionary, eligible: false)
        let userID = "dictionary-card-test-\(UUID().uuidString)"
        ReviewSessionStore.clear(userID: userID)
        defer { ReviewSessionStore.clear(userID: userID) }

        let state = TodayReviewState(
            entries: [dictionary, learning],
            allEntries: [dictionary, learning],
            currentUserID: userID
        )

        #expect(state.queue.map(\.word) == ["learn"])
    }

    @Test("default and difficulty sorting place dictionary cards last")
    func dictionarySortPlacement() {
        let dictionary = entry("aardvark", role: .dictionary, eligible: false)
        let learning = entry("zebra")

        let defaultWords = VocabularyEntryPresentation.sortAndFilter(
            [dictionary, learning], searchText: "", sortOption: .default, now: .now
        ).map(\.word)
        let difficultyWords = VocabularyEntryPresentation.sortAndFilter(
            [dictionary, learning], searchText: "", sortOption: .difficulty, now: .now
        ).map(\.word)
        let alphabeticalWords = VocabularyEntryPresentation.sortAndFilter(
            [dictionary, learning], searchText: "", sortOption: .alphabetical, now: .now
        ).map(\.word)

        #expect(defaultWords == ["zebra", "aardvark"])
        #expect(difficultyWords == ["zebra", "aardvark"])
        #expect(alphabeticalWords == ["aardvark", "zebra"])
    }

    @Test("notebook totals include dictionary cards but review metrics do not")
    func notebookStats() {
        let learning = entry("learn")
        let dictionary = entry("reference", role: .dictionary, eligible: false)

        let stats = NotebookStatsCalculator.compute(
            [learning, dictionary], pendingEntries: [], now: .now
        )["default"]

        #expect(stats?.cardCount == 2)
        #expect((stats?.dueCount ?? 0) + (stats?.unlearnedCount ?? 0) + (stats?.reviewedCount ?? 0) == 1)
        let filtered = NotebookStatsCalculator.filtered(
            [learning, dictionary], filter: NotebookFilter(), now: .now
        )
        #expect(filtered.due.count + filtered.unlearned.count == 1)
    }

    @Test("highlight signature captures eligibility and lexical forms")
    func highlightSignature() {
        let value = entry("run", role: .dictionary, eligible: false)
        value.rootForm = "run"
        value.inflections = ["ran", "running"]
        let visible = VocabularyHighlightSignature.make(entries: [value], notebookId: "default")

        value.isExcludedFromReader = true
        let hidden = VocabularyHighlightSignature.make(entries: [value], notebookId: "default")

        #expect(visible != hidden)
        #expect(visible.contains("running"))
    }

    @MainActor
    @Test("review payloads exclude dictionary cards")
    func reviewPayloadExclusion() async throws {
        let schema = Schema([VocabularyEntry.self, ReviewRecord.self])
        let configuration = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        let container = try ModelContainer(for: schema, configurations: [configuration])
        let context = ModelContext(container)

        let learning = entry("learn")
        learning.kgCardId = "card-learn"
        let dictionary = entry("reference", role: .dictionary, eligible: false)
        dictionary.kgCardId = "card-reference"
        context.insert(learning)
        context.insert(dictionary)
        context.insert(ReviewRecord(word: learning.word, entryID: learning.id, feedback: 1, kgCardId: learning.kgCardId))
        context.insert(ReviewRecord(word: dictionary.word, entryID: dictionary.id, feedback: 1, kgCardId: dictionary.kgCardId))
        try context.save()

        let actor = BackgroundSyncActor(modelContainer: container)
        let statePayload = try await actor.buildReviewStatePushPayload()
        let eventPayload = try await actor.buildReviewEventsPushPayload()

        #expect(statePayload.compactMap { $0["word"] as? String } == ["learn"])
        #expect(eventPayload.map(\.word_snapshot) == ["learn"])
    }
}

@Suite("Dictionary card V1 wire format")
struct DictionaryCardWireTests {
    @Test("dictionary projection decodes provenance and selected example")
    func decodeProjection() throws {
        let data = Data(Self.payload.utf8)
        let projection = try JSONDecoder().decode(KGDictionaryCardProjection.self, from: data)

        #expect(projection.card.id == "card-1")
        #expect(projection.dictionaryEntry.provider == "free_dictionary")
        #expect(projection.dictionaryEntry.senses.first?.examples.first?.text == "A lucid answer.")
        #expect(projection.selectedSenseKey == "sense-1")
        #expect(projection.card.cardRole == "dictionary")
        #expect(projection.card.reviewEligible == false)
    }

    private static let payload = """
    {
      "card": {
        "id": "card-1", "content": "lucid", "meaning": "清晰的", "pos": "adjective",
        "examples": ["A lucid answer."], "mode": "recognition", "notebookId": "default",
        "cardRole": "dictionary", "reviewEligible": false, "readerHidden": false,
        "promotionState": "idle"
      },
      "dictionaryEntry": {
        "provider": "free_dictionary", "dictionaryId": "wiktionary-en",
        "entryKey": "free_dictionary:en:lucid", "schemaVersion": 1, "word": "lucid",
        "sourceLanguage": "en", "targetLanguage": "zh-Hant", "pronunciations": [],
        "senses": [{
          "id": "sense-1", "partOfSpeech": "adjective", "definition": "expressed clearly",
          "translations": ["清晰的"],
          "examples": [{"id": "example-1", "text": "A lucid answer."}],
          "synonyms": [], "antonyms": []
        }],
        "forms": [], "sourceUrl": "https://en.wiktionary.org/wiki/lucid",
        "licenseName": "CC BY-SA 4.0", "licenseUrl": "https://creativecommons.org/licenses/by-sa/4.0/",
        "attributionText": "Wiktionary via FreeDictionaryAPI", "fetchedAt": "2026-08-05T00:00:00Z",
        "truncated": false
      },
      "selectedSenseKey": "sense-1", "selectedExampleKey": "example-1",
      "materializationStatus": "active"
    }
    """
}
