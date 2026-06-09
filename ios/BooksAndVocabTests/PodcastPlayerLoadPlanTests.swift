#if os(iOS)
import Foundation
import Testing
@testable import BooksAndVocab

@Suite("PodcastPlayerLoadPlan")
struct PodcastPlayerLoadPlanTests {
    @Test func localAudioWinsOverRemoteAudioAndNeedsNoAuthHeaders() throws {
        let episode = makeEpisode()
        episode.localAudioPath = "/tmp/local-audio.m4a"
        episode.audioURL = "https://example.com/remote.m4a"

        let plan = try #require(PodcastPlayerLoadPlan.make(episode: episode, fileExists: { $0 == "/tmp/local-audio.m4a" }))

        #expect(plan.audioURL.isFileURL)
        #expect(plan.audioURL.path == "/tmp/local-audio.m4a")
        #expect(plan.usesLocalAudio)
    }

    @Test func missingLocalAudioFallsBackToRemoteAudio() throws {
        let episode = makeEpisode()
        episode.localAudioPath = "/tmp/missing.m4a"
        episode.audioURL = "https://example.com/remote.m4a"

        let plan = try #require(PodcastPlayerLoadPlan.make(episode: episode, fileExists: { _ in false }))

        #expect(plan.audioURL == URL(string: "https://example.com/remote.m4a"))
        #expect(plan.usesLocalAudio == false)
    }

    @Test func missingAllAudioReturnsNil() {
        let episode = makeEpisode()

        #expect(PodcastPlayerLoadPlan.make(episode: episode, fileExists: { _ in false }) == nil)
    }

    @Test func inlineSubtitleWinsOverRemoteSubtitle() throws {
        let episode = makeEpisode()
        episode.audioURL = "https://example.com/audio.m4a"
        episode.inlineSubtitle = "1\n00:00:00,000 --> 00:00:01,000\nHi"
        episode.subtitleURL = "https://example.com/subtitle.srt"

        let plan = try #require(PodcastPlayerLoadPlan.make(episode: episode))

        #expect(plan.subtitleSource == .inline("1\n00:00:00,000 --> 00:00:01,000\nHi"))
    }

    @Test func emptyInlineSubtitleFallsBackToRemoteSubtitle() throws {
        let episode = makeEpisode()
        episode.audioURL = "https://example.com/audio.m4a"
        episode.inlineSubtitle = ""
        episode.subtitleURL = "https://example.com/subtitle.srt"

        let plan = try #require(PodcastPlayerLoadPlan.make(episode: episode))

        #expect(plan.subtitleSource == .remote("https://example.com/subtitle.srt"))
    }

    @Test func missingSubtitleIsExplicitlyUnavailable() throws {
        let episode = makeEpisode()
        episode.audioURL = "https://example.com/audio.m4a"

        let plan = try #require(PodcastPlayerLoadPlan.make(episode: episode))

        #expect(plan.subtitleSource == .unavailable)
    }

    private func makeEpisode() -> PodcastEpisode {
        PodcastEpisode(remoteId: "series_ep_1", episodeNumber: 1, title: "Pilot", durationSec: 42)
    }
}
#endif
