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
        // Authenticated endpoint with HTTP Range support. AVPlayer attaches the
        // Bearer token via `AVURLAssetHTTPHeaderFieldsKey` (see `PodcastPlayerView`).
        "\(baseURL)/api/podcasts/\(seriesId)/\(episodeNumber)/audio"
    }

    static func subtitleURL(seriesId: String, episodeNumber: Int) -> String {
        "\(baseURL)/api/podcasts/\(seriesId)/\(episodeNumber)/subtitle"
    }

    /// Shared helper so `PodcastPlayerView` 的 subtitle / audio metadata fetch 也能重用。
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

    /// Full sync: fetch all series, upsert into SwiftData, then reconcile orphans.
    /// Detail fetch failures for individual series are swallowed — we still
    /// upsert what succeeded and feed only the succeeded set to reconcile so
    /// transient 404/timeout cannot trigger episode mass-deletion.
    @MainActor
    func syncAll(context: ModelContext) async {
        let summaries: [PodcastSeriesSummary]
        do {
            summaries = try await fetchSeriesList()
        } catch {
            // List fetch failure → skip reconcile (空 list 會誤刪所有 series).
            AppLog.kg.warning("[PodcastSync] list fetch failed: \(error.localizedDescription)")
            if !(error is CancellationError) {
                AppCrashReporting.record(error, context: "podcast.sync.list")
            }
            return
        }
        var details: [String: PodcastSeriesDetail] = [:]
        for summary in summaries {
            do {
                let detail = try await fetchSeriesDetail(seriesId: summary.id)
                details[summary.id] = detail
                upsertSeries(detail: detail, context: context)
            } catch {
                AppLog.kg.warning("[PodcastSync] detail fetch failed for \(summary.id): \(error.localizedDescription)")
                if !(error is CancellationError) {
                    AppCrashReporting.record(error, context: "podcast.sync.detail")
                }
            }
        }
        Self.reconcileLocalState(
            serverSummaries: summaries,
            fetchedDetails: details,
            context: context
        )
        do {
            try context.save()
        } catch {
            AppLog.kg.warning("[PodcastSync] context save failed: \(error.localizedDescription)")
            AppCrashReporting.record(error, context: "podcast.sync.save")
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
        // Resurrect: if server brings a previously-tombstoned series back, clear flag.
        if series.isDeleted { series.isDeleted = false }

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

    // MARK: - Reconcile / Sanitize

    /// Collapse duplicate `PodcastProgress` rows for a single episode into one.
    /// CloudKit lacks unique constraints (see commit fd28be0), so two devices
    /// can legally insert sibling rows for the same episode. Always call this
    /// before reading/writing progress to converge the store.
    /// Returns the surviving (newest) row, or nil if none exists.
    @MainActor
    @discardableResult
    static func sanitizeProgressDuplicates(
        for episodeRemoteId: String,
        context: ModelContext
    ) -> PodcastProgress? {
        let targetId = episodeRemoteId
        let descriptor = FetchDescriptor<PodcastProgress>(
            predicate: #Predicate { $0.episodeRemoteId == targetId },
            sortBy: [SortDescriptor(\.updatedAt, order: .reverse)]
        )
        guard let rows = try? context.fetch(descriptor), !rows.isEmpty else {
            return nil
        }
        // Tie-break: same updatedAt → keep the row with larger lastPlayedTime
        // (closer to user's true progress).
        let newest = rows.first!
        let tied = rows.filter { $0.updatedAt == newest.updatedAt }
        let winner: PodcastProgress = tied.count > 1
            ? (tied.max(by: { $0.lastPlayedTime < $1.lastPlayedTime }) ?? newest)
            : newest
        for row in rows where row !== winner {
            context.delete(row)
        }
        return winner
    }

    /// Reconcile local SwiftData state against authoritative server data.
    /// - `serverSummaries` — full set returned by `fetchSeriesList()`.
    /// - `fetchedDetails` — only series whose detail fetch succeeded; series
    ///   missing here are NOT touched at episode level (防 detail 短暫 404 誤刪).
    ///
    /// Behavior:
    /// 1. Series tombstone: local series not in `serverSummaries` → soft-delete (`isDeleted = true`).
    /// 2. Series resurrection: tombstoned local series back in `serverSummaries` → clear flag.
    /// 3. Episode hard-delete: per fetched detail, drop local episodes missing from server.
    /// 4. Orphan progress sweep: drop `PodcastProgress` rows whose episode no longer exists.
    /// 5. Per-episode duplicate sweep across all surviving episodes.
    @MainActor
    static func reconcileLocalState(
        serverSummaries: [PodcastSeriesSummary],
        fetchedDetails: [String: PodcastSeriesDetail],
        context: ModelContext
    ) {
        let serverSeriesIds = Set(serverSummaries.map(\.id))

        // 1 + 2: Series tombstone / resurrection
        let allSeriesDescriptor = FetchDescriptor<PodcastSeries>()
        let allSeries = (try? context.fetch(allSeriesDescriptor)) ?? []
        for series in allSeries {
            let onServer = serverSeriesIds.contains(series.remoteId)
            if onServer && series.isDeleted {
                series.isDeleted = false
                series.updatedAt = Date()
            } else if !onServer && !series.isDeleted {
                series.isDeleted = true
                series.updatedAt = Date()
            }
        }

        // 3: Episode hard-delete (only for series whose detail we fetched)
        // Empty `detail.episodes` is treated as a transient server hiccup and
        // skipped — otherwise we'd nuke every local episode + orphan all progress.
        for (seriesId, detail) in fetchedDetails {
            guard !detail.episodes.isEmpty else {
                AppLog.kg.warning("[PodcastSync] skip episode reconcile for \(seriesId) — server returned empty episodes")
                continue
            }
            let serverEpRemoteIds = Set(detail.episodes.map {
                Self.episodeRemoteId(seriesId: seriesId, episodeNumber: $0.episodeNumber)
            })
            let epDescriptor = FetchDescriptor<PodcastEpisode>(
                predicate: #Predicate { $0.series?.remoteId == seriesId }
            )
            let localEps = (try? context.fetch(epDescriptor)) ?? []
            for ep in localEps where !serverEpRemoteIds.contains(ep.remoteId) {
                context.delete(ep)
            }
        }

        // 4 + 5: Single-fetch orphan sweep + in-memory dedup grouping.
        // Avoids O(N) per-episode fetch (was painful at 1000+ episodes).
        let epDescriptor = FetchDescriptor<PodcastEpisode>()
        let liveEpIds = Set(((try? context.fetch(epDescriptor)) ?? []).map(\.remoteId))
        let progressDescriptor = FetchDescriptor<PodcastProgress>()
        let allProgress = (try? context.fetch(progressDescriptor)) ?? []

        var grouped: [String: [PodcastProgress]] = [:]
        for p in allProgress {
            if liveEpIds.contains(p.episodeRemoteId) {
                grouped[p.episodeRemoteId, default: []].append(p)
            } else {
                context.delete(p)
            }
        }
        for (_, rows) in grouped where rows.count > 1 {
            let sorted = rows.sorted { $0.updatedAt > $1.updatedAt }
            let newest = sorted.first!
            let tied = sorted.filter { $0.updatedAt == newest.updatedAt }
            let winner: PodcastProgress = tied.count > 1
                ? (tied.max(by: { $0.lastPlayedTime < $1.lastPlayedTime }) ?? newest)
                : newest
            for row in rows where row !== winner {
                context.delete(row)
            }
        }
    }
}
