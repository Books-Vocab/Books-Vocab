import Foundation
import SwiftData

// MARK: - API Response Models

struct PodcastSeriesSummary: Codable {
    let id: String
    let title: String
    let author: String?
    let hostNames: [String]?
    let color: String?
    let coverPattern: String?
    let totalDurationSec: Double?
    let episodeCount: Int?
}

struct PodcastSeriesDetail: Codable {
    let id: String
    let title: String
    let author: String?
    let hostNames: [String]?
    let color: String?
    let coverPattern: String?
    let totalDurationSec: Double?
    let episodes: [PodcastEpisodeDetail]
    let createdAt: String?
    let updatedAt: String?
}

struct PodcastEpisodeDetail: Codable {
    let episodeNumber: Int
    let title: String
    let durationSec: Double
    let audioAvailable: Bool
    let subtitleAvailable: Bool
}

// MARK: - Sync Service

final class PodcastSyncService {
    private static let baseURL = AppURLs.domain

    private let kgService: any KGServing

    init(kgService: any KGServing) {
        self.kgService = kgService
    }

    static func episodeRemoteId(seriesId: String, episodeNumber: Int) -> String {
        "\(seriesId)_ep_\(String(format: "%02d", episodeNumber))"
    }

    static func audioURL(seriesId: String, episodeNumber: Int) -> String {
        "\(baseURL)/api/podcast-media/\(seriesId)/ep_\(String(format: "%02d", episodeNumber))/audio.mp3"
    }

    static func subtitleURL(seriesId: String, episodeNumber: Int) -> String {
        "\(baseURL)/api/podcasts/\(seriesId)/\(episodeNumber)/subtitle"
    }

    /// Shared helper so `PodcastPlayerView` 的 subtitle fetch 也能重用。
    /// `/api/podcast-media/` StaticFiles mount 例外 — Starlette mount 旁路 FastAPI
    /// dependency，audio.mp3 目前仍為公開（後續 PR 改自訂 endpoint 時再補 auth）。
    static func authedData(from urlString: String, kgService: any KGServing) async throws -> Data {
        guard let url = URL(string: urlString) else {
            throw URLError(.badURL)
        }
        let token = try await kgService.currentAuthToken()
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.addValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let (data, _) = try await URLSession.shared.data(for: request)
        return data
    }

    func fetchSeriesList() async throws -> [PodcastSeriesSummary] {
        let data = try await Self.authedData(from: "\(Self.baseURL)/api/podcasts", kgService: kgService)
        return try JSONDecoder().decode([PodcastSeriesSummary].self, from: data)
    }

    func fetchSeriesDetail(seriesId: String) async throws -> PodcastSeriesDetail {
        let data = try await Self.authedData(from: "\(Self.baseURL)/api/podcasts/\(seriesId)", kgService: kgService)
        return try JSONDecoder().decode(PodcastSeriesDetail.self, from: data)
    }

    /// Full sync: fetch all series then upsert into SwiftData.
    @MainActor
    func syncAll(context: ModelContext) async {
        do {
            let summaries = try await fetchSeriesList()
            for summary in summaries {
                let detail = try await fetchSeriesDetail(seriesId: summary.id)
                upsertSeries(detail: detail, context: context)
            }
            try context.save()
        } catch {
            // Best-effort — podcast sync must not block the app
            AppLog.kg.warning("[PodcastSync] sync failed: \(error.localizedDescription)")
        }
    }

    @MainActor
    private func upsertSeries(detail: PodcastSeriesDetail, context: ModelContext) {
        let seriesId = detail.id
        let descriptor = FetchDescriptor<PodcastSeries>(
            predicate: #Predicate { $0.remoteId == seriesId }
        )
        let existing = try? context.fetch(descriptor)
        let series: PodcastSeries

        if let found = existing?.first {
            series = found
        } else {
            series = PodcastSeries(
                remoteId: detail.id,
                title: detail.title,
                hostNames: detail.hostNames ?? []
            )
            context.insert(series)
        }

        series.title = detail.title
        series.hostNames = detail.hostNames ?? []
        series.color = detail.color
        series.coverPattern = detail.coverPattern
        series.totalDurationSec = detail.totalDurationSec ?? 0
        series.episodeCount = detail.episodes.count
        series.updatedAt = Date()

        for ep in detail.episodes {
            let epRemoteId = Self.episodeRemoteId(seriesId: detail.id, episodeNumber: ep.episodeNumber)
            let epDescriptor = FetchDescriptor<PodcastEpisode>(
                predicate: #Predicate { $0.remoteId == epRemoteId }
            )
            let existingEp = try? context.fetch(epDescriptor)
            let episode: PodcastEpisode

            if let found = existingEp?.first {
                episode = found
            } else {
                episode = PodcastEpisode(
                    remoteId: epRemoteId,
                    episodeNumber: ep.episodeNumber,
                    title: ep.title,
                    durationSec: ep.durationSec
                )
                context.insert(episode)
            }

            episode.episodeNumber = ep.episodeNumber
            episode.title = ep.title
            episode.durationSec = ep.durationSec
            episode.audioAvailable = ep.audioAvailable
            episode.subtitleAvailable = ep.subtitleAvailable
            episode.audioURL = Self.audioURL(seriesId: detail.id, episodeNumber: ep.episodeNumber)
            episode.subtitleURL = Self.subtitleURL(seriesId: detail.id, episodeNumber: ep.episodeNumber)
            episode.series = series
        }
    }
}
