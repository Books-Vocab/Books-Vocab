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

    @Test func episode_remote_id_format() {
        let remoteId = PodcastSyncService.episodeRemoteId(seriesId: "flow_950f1a7d", episodeNumber: 1)
        #expect(remoteId == "flow_950f1a7d_ep_01")
    }

    @Test func audio_url_format() {
        let url = PodcastSyncService.audioURL(seriesId: "flow_950f1a7d", episodeNumber: 1)
        #expect(url == "https://wordnexus.lol/api/podcast-media/flow_950f1a7d/ep_01/audio.mp3")
    }

    @Test func subtitle_url_format() {
        let url = PodcastSyncService.subtitleURL(seriesId: "flow_950f1a7d", episodeNumber: 1)
        #expect(url == "https://wordnexus.lol/api/podcasts/flow_950f1a7d/1/subtitle")
    }
}
