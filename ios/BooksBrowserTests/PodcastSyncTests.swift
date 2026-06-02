import Foundation
import Testing
@testable import BooksBrowser

struct PodcastSyncTests {
    @Test func parse_series_list_response() throws {
        let json = """
        [{"id":"flow_950f1a7d","title":"Flow","author":"Csikszentmihalyi","episodeCount":8,"hostNames":["Maya","Kai"],"color":"#5B8C5A","coverPattern":"waves","totalDurationSec":11700}]
        """.data(using: .utf8)!
        let series = try JSONDecoder().decode([PodcastSeriesSummary].self, from: json)
        #expect(series.count == 1)
        #expect(series[0].id == "flow_950f1a7d")
        #expect(series[0].hostNames == ["Maya", "Kai"])
    }

    @Test func parse_series_detail_response() throws {
        let json = """
        {"id":"flow_950f1a7d","title":"Flow","author":"Csikszentmihalyi",
         "hostNames":["Maya","Kai"],"color":"#5B8C5A","coverPattern":"waves",
         "totalDurationSec":11700,
         "episodes":[{"episodeNumber":1,"title":"The Happiness Trap","durationSec":1420,"audioAvailable":true,"subtitleAvailable":true}],
         "createdAt":"2026-04-12T20:00:00Z","updatedAt":"2026-04-12T21:30:00Z"}
        """.data(using: .utf8)!
        let detail = try JSONDecoder().decode(PodcastSeriesDetail.self, from: json)
        #expect(detail.episodes.count == 1)
        #expect(detail.episodes[0].title == "The Happiness Trap")
    }

    @Test func episode_detail_tolerates_missing_optional_fields() throws {
        // S3 metadata.json is hand-assembled by ops/podcast_upload.sh (not
        // Pydantic-validated). A single episode missing durationSec /
        // audioAvailable / subtitleAvailable must NOT fail the whole series
        // decode — graceful-degrade with safe defaults instead.
        let json = """
        {"id":"flow_950f1a7d","title":"Flow",
         "episodes":[{"episodeNumber":3,"title":"Partial Episode"}]}
        """.data(using: .utf8)!
        let detail = try JSONDecoder().decode(PodcastSeriesDetail.self, from: json)
        #expect(detail.episodes.count == 1)
        let ep = detail.episodes[0]
        #expect(ep.episodeNumber == 3)
        #expect(ep.title == "Partial Episode")
        #expect(ep.durationSec == 0)
        #expect(ep.audioAvailable == false)
        #expect(ep.subtitleAvailable == false)
        #expect(ep.subtitleContent == nil)
    }

    @Test func episode_detail_still_requires_identity_fields() {
        // episodeNumber / title are identity-critical — a missing one makes the
        // episode meaningless, so that single episode's decode SHOULD throw.
        let json = """
        {"id":"x","title":"X",
         "episodes":[{"durationSec":100,"audioAvailable":true,"subtitleAvailable":false}]}
        """.data(using: .utf8)!
        #expect(throws: (any Error).self) {
            try JSONDecoder().decode(PodcastSeriesDetail.self, from: json)
        }
    }

    @Test func episode_remote_id_format() {
        let remoteId = PodcastSyncService.episodeRemoteId(seriesId: "flow_950f1a7d", episodeNumber: 1)
        #expect(remoteId == "flow_950f1a7d_ep_01")
    }

    @Test func audio_url_format() {
        // Authenticated endpoint replaces the public StaticFiles path.
        let url = PodcastSyncService.audioURL(seriesId: "flow_950f1a7d", episodeNumber: 1)
        #expect(url == "https://wordnexus.lol/api/podcasts/flow_950f1a7d/1/audio")
    }

    @Test func subtitle_url_format() {
        let url = PodcastSyncService.subtitleURL(seriesId: "flow_950f1a7d", episodeNumber: 1)
        #expect(url == "https://wordnexus.lol/api/podcasts/flow_950f1a7d/1/subtitle")
    }
}
