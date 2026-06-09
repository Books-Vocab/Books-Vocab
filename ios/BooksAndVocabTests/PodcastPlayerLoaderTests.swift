#if os(iOS)
import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@Suite("PodcastPlayerLoader")
struct PodcastPlayerLoaderTests {
    @Test func inlineSubtitlePassesThroughWithoutRemoteFetch() async {
        let subtitle = await PodcastPlayerLoader.resolveSubtitle(
            from: .inline("inline subtitle"),
            kgService: StubKGService()
        ) { _, _ in
            Issue.record("remote subtitle fetch should not run for inline subtitles")
            return nil
        }

        #expect(subtitle == .content("inline subtitle"))
    }

    @Test func remoteSubtitleFailureIsExplicit() async {
        let subtitle = await PodcastPlayerLoader.resolveSubtitle(
            from: .remote("https://example.com/subtitle.srt"),
            kgService: StubKGService()
        ) { _, _ in
            nil
        }

        #expect(subtitle == .failed)
    }

    @Test func unavailableSubtitleStaysUnavailable() async {
        let subtitle = await PodcastPlayerLoader.resolveSubtitle(
            from: .unavailable,
            kgService: StubKGService()
        )

        #expect(subtitle == .unavailable)
    }

    @Test func localAudioNeedsNoAuthHeaderLookup() async throws {
        let episode = makeEpisode()
        episode.localAudioPath = "/tmp/local-audio.m4a"
        let plan = try #require(PodcastPlayerLoadPlan.make(episode: episode, fileExists: { _ in true }))

        let headers = try await PodcastPlayerLoader.resolveAudioHeaders(
            for: plan,
            kgService: StubKGService()
        ) { _ in
            Issue.record("token provider should not run for local audio")
            return "unused"
        }

        #expect(headers.isEmpty)
    }

    @Test func remoteAudioUsesBearerToken() async throws {
        let episode = makeEpisode()
        episode.audioURL = "https://example.com/audio.m4a"
        let plan = try #require(PodcastPlayerLoadPlan.make(episode: episode))

        let headers = try await PodcastPlayerLoader.resolveAudioHeaders(
            for: plan,
            kgService: StubKGService()
        ) { _ in
            "secret-token"
        }

        #expect(headers == ["Authorization": "Bearer secret-token"])
    }

    private func makeEpisode() -> PodcastEpisode {
        PodcastEpisode(remoteId: "series_ep_1", episodeNumber: 1, title: "Pilot", durationSec: 42)
    }
}

private final class StubKGService: KGServing {
    var lastBackgroundSyncError: String?
    var serverURL: String = "https://example.com"
    var isConnected: Bool = true
    var lastSyncDate: Date?
    var serverCardCount: Int = 0
    var sessionExpiredReason: String?

    func currentAuthToken() async throws -> String { "token" }
    func backgroundSync(container: ModelContainer) async {}
    func healthCheck() async {}
    func batchAdd(entries: [VocabularyEntry], notebookId: String) async throws -> KGAddResponse { fatalError("unused") }
    func triggerPipeline(notebookId: String) async throws { fatalError("unused") }
    func pullCardsToLocal(container: ModelContainer, progress: ((String, Int, Int) -> Void)?, notebookId: String?) async throws -> Bool { fatalError("unused") }
    func fetchNotebooks() async throws -> [KGNotebook] { fatalError("unused") }
    func createNotebook(name: String, color: String?, coverPattern: String?) async throws -> KGNotebook { fatalError("unused") }
    func updateNotebook(id: String, name: String?, color: String?, coverPattern: String?) async throws -> KGNotebook { fatalError("unused") }
    func deleteNotebook(id: String) async throws { fatalError("unused") }
    func fetchUserConfig() async throws -> KGUserConfig { fatalError("unused") }
    func fetchEntitlements() async throws -> KGEntitlements { fatalError("unused") }
    func syncAppStoreSubscription(_ snapshot: KGAppStoreSubscriptionSyncRequest) async throws -> KGEntitlements { fatalError("unused") }
    func updateTranslationConfig(_ translationConfig: KGTranslationConfig) async throws -> KGUserConfig { fatalError("unused") }
    func updateReviewClockConfig(_ reviewClock: KGReviewClockConfig) async throws -> KGUserConfig { fatalError("unused") }
    func updateReviewModeConfig(_ reviewMode: KGReviewModeConfig) async throws -> KGUserConfig { fatalError("unused") }
    func updateVocabUIConfig(_ vocabUI: KGVocabUIConfig) async throws -> KGUserConfig { fatalError("unused") }
    func deleteAccount() async throws { fatalError("unused") }
    func pullGraphLinks() async throws -> [KGGraphLink] { fatalError("unused") }
    func createManualLink(fromId: String, toId: String, notebookId: String) async throws -> KGGraphLink { fatalError("unused") }
    func deleteLink(linkId: String, notebookId: String) async throws { fatalError("unused") }
    func hideLink(linkId: String, notebookId: String) async throws { fatalError("unused") }
    func unhideLink(linkId: String, notebookId: String) async throws { fatalError("unused") }
    func deleteCard(word: String, notebookId: String) async throws { fatalError("unused") }
    func batchDeleteCards(words: [String], notebookId: String) async throws -> KGBatchDeleteResponse { fatalError("unused") }
    func archiveCard(word: String, archived: Bool, notebookId: String) async throws { fatalError("unused") }
    func batchArchiveCards(words: [String], archived: Bool, notebookId: String) async throws -> KGBatchArchiveResponse { fatalError("unused") }
    func pushReviewStates(container: ModelContainer) async throws -> (updated: Int, skipped: Int) { fatalError("unused") }
    func pushReviewEvents(container: ModelContainer) async throws -> (inserted: Int, skipped: Int) { fatalError("unused") }
    func pullReviewEvents(container: ModelContainer) async throws { fatalError("unused") }
    func pushReviewQuietly(container: ModelContainer) async {}
    func clearLocalData(container: ModelContainer, reason: String) async {}
    func fetchQuota() async {}
}
#endif
