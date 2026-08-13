import Testing
@testable import BooksAndVocab

struct SettingsMutationGenerationTests {
    @Test func newerIntentInvalidatesOlderRollbackToken() {
        var generation = SettingsMutationGeneration()

        let first = generation.begin()
        let second = generation.begin()

        #expect(!generation.accepts(first))
        #expect(generation.accepts(second))
    }

    @Test func currentIntentRemainsValidUntilNextIntent() {
        var generation = SettingsMutationGeneration()
        let token = generation.begin()

        #expect(generation.accepts(token))
    }
}
