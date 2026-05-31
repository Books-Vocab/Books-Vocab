import Foundation
import Testing
@testable import BooksBrowser

@MainActor
@Suite("PodcastDetailRouter")
struct PodcastDetailRouterTests {
    @Test func defaultHasNoDetail() {
        let r = PodcastDetailRouter()
        #expect(r.selectedEpisodeRemoteId == nil)
        #expect(r.hasDetail == false)
    }

    @Test func showDrivesHasDetail() {
        let r = PodcastDetailRouter()
        r.show(episodeRemoteId: "ep-1")
        #expect(r.selectedEpisodeRemoteId == "ep-1")
        #expect(r.hasDetail == true)
    }

    @Test func dismissClearsSelection() {
        let r = PodcastDetailRouter()
        r.show(episodeRemoteId: "ep-1")
        r.dismiss()
        #expect(r.selectedEpisodeRemoteId == nil)
        #expect(r.hasDetail == false)
    }

    @Test func showReplacesSelection() {
        let r = PodcastDetailRouter()
        r.show(episodeRemoteId: "ep-1")
        r.show(episodeRemoteId: "ep-2")
        #expect(r.selectedEpisodeRemoteId == "ep-2")
    }
}
