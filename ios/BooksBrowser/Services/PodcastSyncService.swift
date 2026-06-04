import Foundation
import SwiftData

extension Notification.Name {
    /// Posted by `PodcastSyncService.syncAll` after a successful catalog
    /// reconcile (`.completed`). Views that froze their `@Query` into a
    /// one-shot `@State` snapshot (see `PodcastEpisodeListView`'s freeze-fix)
    /// listen for this to discretely re-read the store — `seriesId` is stable
    /// across a background upsert so `.task(id:)` won't re-fire on its own.
    static let podcastCatalogDidSync = Notification.Name("podcastCatalogDidSync")
}

// MARK: - API Response Models

struct PodcastSeriesSummary: Codable {
    let id: String
    let title: String
    let author: String?
    let hostNames: [String]?
    let color: String?
    let coverPattern: String?
    let coverImageURL: String?
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
    let coverImageURL: String?
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
    /// SRT content inlined by `ops/podcast_upload.sh`. When present the
    /// player skips the per-episode subtitle fetch entirely. Optional —
    /// older series uploaded before the embed change won't carry it.
    let subtitleContent: String?

    private enum CodingKeys: String, CodingKey {
        case episodeNumber, title, durationSec, audioAvailable, subtitleAvailable, subtitleContent
    }

    init(
        episodeNumber: Int,
        title: String,
        durationSec: Double,
        audioAvailable: Bool,
        subtitleAvailable: Bool,
        subtitleContent: String?
    ) {
        self.episodeNumber = episodeNumber
        self.title = title
        self.durationSec = durationSec
        self.audioAvailable = audioAvailable
        self.subtitleAvailable = subtitleAvailable
        self.subtitleContent = subtitleContent
    }

    /// Custom decode for resilience against hand-assembled S3 metadata.json
    /// (`ops/podcast_upload.sh` stitches it by hand — no Pydantic guarantee).
    /// One episode dropping a non-identity field used to throw and make the
    /// *entire series* invisible (whole-detail decode is all-or-nothing, and
    /// `syncAll` swallows the per-series failure). Identity fields
    /// (`episodeNumber` / `title`) stay required — a missing one makes the
    /// episode meaningless. The rest graceful-degrade to safe defaults:
    /// - `durationSec` → 0 (renders 0:00; the only divisor site,
    ///   `PodcastEpisodeRow.progressFraction`, is guarded by `durationSec > 0`,
    ///   so 0 cannot divide-by-zero).
    /// - `audioAvailable` → false (shows non-playable, far better than the
    ///   whole series vanishing).
    /// - `subtitleAvailable` → false (no subtitle).
    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        episodeNumber = try c.decode(Int.self, forKey: .episodeNumber)
        title = try c.decode(String.self, forKey: .title)
        durationSec = try c.decodeIfPresent(Double.self, forKey: .durationSec) ?? 0
        audioAvailable = try c.decodeIfPresent(Bool.self, forKey: .audioAvailable) ?? false
        subtitleAvailable = try c.decodeIfPresent(Bool.self, forKey: .subtitleAvailable) ?? false
        subtitleContent = try c.decodeIfPresent(String.self, forKey: .subtitleContent)
    }
}

// MARK: - Sync Service

final class PodcastSyncService {
    private static let baseURL = AppURLs.domain

    // 同檔案以外的 extension（如 PodcastProgressSync.swift）需要 access；
    // 改 internal 不對外暴露，僅在 module 內可見。
    let kgService: any KGServing

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
        let (data, _) = try await sharedURLSession.data(for: request)
        return data
    }

    // MARK: - Cover image cache (remote → local file, rendered by NotebookCoverView)

    /// `Documents/podcast-covers/` — downloaded series covers. Documents (not
    /// Caches) so the file survives backgrounding and matches the audio-download
    /// convention; `LocalDataCleanerService` purges this tree on logout /
    /// account-switch so a reused remoteId can't leak account A's cover to B.
    static func coversRoot() -> URL {
        FileManager.default
            .urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("podcast-covers", isDirectory: true)
    }

    static func cachedCoverURL(seriesId: String) -> URL {
        Self.coversRoot().appendingPathComponent("\(seriesId).png")
    }

    /// Best-effort: download the remote cover into the local cache and point
    /// `coverImagePath` at it, so `NotebookCoverView` renders the photo over the
    /// procedural cover. No-op when the series has no remote cover or the file is
    /// already cached. Failures are logged, never thrown — a missing/blocked
    /// cover must degrade to the procedural cover, not break the sync pass.
    @MainActor
    static func cacheCoverIfNeeded(
        seriesId: String, context: ModelContext, kgService: any KGServing
    ) async {
        let descriptor = FetchDescriptor<PodcastSeries>(
            predicate: #Predicate { $0.remoteId == seriesId }
        )
        guard let series = try? context.fetch(descriptor).first,
              let remote = series.coverImageURL, !remote.isEmpty else { return }

        let cacheURL = Self.cachedCoverURL(seriesId: seriesId)
        // Already cached + on disk → reuse (a series cover is stable).
        if series.coverImagePath == cacheURL.path,
           FileManager.default.fileExists(atPath: cacheURL.path) {
            return
        }

        let urlString = remote.hasPrefix("http") ? remote : "\(baseURL)\(remote)"
        do {
            let data = try await authedData(from: urlString, kgService: kgService)
            // PNG magic — a 404 / HTML / JSON error body must never be written as
            // a "cover" (silent-garbage guard, not a silent fallback).
            guard data.count > 8, Array(data.prefix(4)) == [0x89, 0x50, 0x4E, 0x47] else {
                AppLog.kg.warning("[PodcastSync] cover for \(seriesId) not a PNG; skipped")
                return
            }
            try FileManager.default.createDirectory(
                at: Self.coversRoot(), withIntermediateDirectories: true
            )
            try data.write(to: cacheURL, options: .atomic)
            series.coverImagePath = cacheURL.path
        } catch is CancellationError {
            return
        } catch {
            AppLog.kg.warning("[PodcastSync] cover fetch failed for \(seriesId): \(error.localizedDescription)")
        }
    }

    func fetchSeriesList() async throws -> [PodcastSeriesSummary] {
        let data = try await Self.authedData(from: "\(Self.baseURL)/api/podcasts", kgService: kgService)
        return try JSONDecoder().decode([PodcastSeriesSummary].self, from: data)
    }

    func fetchSeriesDetail(seriesId: String) async throws -> PodcastSeriesDetail {
        let data = try await Self.authedData(from: "\(Self.baseURL)/api/podcasts/\(seriesId)", kgService: kgService)
        return try JSONDecoder().decode(PodcastSeriesDetail.self, from: data)
    }

    /// Outcome of a `syncAll` pass. Only the list fetch is fatal (a complete
    /// no-op refresh the user explicitly triggered); detail / progress / save
    /// failures are partial or auxiliary and stay swallowed as before.
    enum SyncOutcome: Equatable {
        /// List fetch returned (catalog reconciled); refresh did something.
        case completed
        /// Cancelled mid-flight (view torn down / task superseded) — not an error.
        case cancelled
        /// Series-list fetch failed → nothing refreshed. Surface to user when
        /// the sync was an explicit pull-to-refresh.
        case listFetchFailed
    }

    /// Full sync: fetch all series, upsert into SwiftData, then reconcile orphans.
    /// Detail fetch failures for individual series are swallowed — we still
    /// upsert what succeeded and feed only the succeeded set to reconcile so
    /// transient 404/timeout cannot trigger episode mass-deletion.
    ///
    /// Returns a `SyncOutcome`; callers that ran a silent/background sync ignore
    /// it (`@discardableResult`), while pull-to-refresh checks it to surface a
    /// toast on `.listFetchFailed`.
    @MainActor
    @discardableResult
    func syncAll(context: ModelContext) async -> SyncOutcome {
        let summaries: [PodcastSeriesSummary]
        do {
            summaries = try await fetchSeriesList()
        } catch is CancellationError {
            // Task superseded / view torn down mid-fetch — not a user-facing error.
            AppLog.kg.warning("[PodcastSync] list fetch cancelled")
            return .cancelled
        } catch {
            // List fetch failure → skip reconcile (空 list 會誤刪所有 series).
            AppLog.kg.warning("[PodcastSync] list fetch failed: \(error.localizedDescription)")
            AppCrashReporting.record(error, context: "podcast.sync.list")
            return .listFetchFailed
        }
        var details: [String: PodcastSeriesDetail] = [:]
        for summary in summaries {
            do {
                let detail = try await fetchSeriesDetail(seriesId: summary.id)
                details[summary.id] = detail
                Self.upsertSeries(detail: detail, context: context)
                // Best-effort remote-cover download into the local cache; failures
                // degrade to the procedural cover and never abort the sync pass.
                await Self.cacheCoverIfNeeded(seriesId: summary.id, context: context, kgService: kgService)
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
        // Pull authoritative cross-device progress and merge under LWW.
        // Failure here must NOT abort the series sync — progress is auxiliary,
        // missing it falls back to local SwiftData like before this endpoint
        // existed.
        do {
            let remote = try await fetchAllProgress()
            Self.mergeRemoteProgress(remote: remote, context: context)
        } catch {
            AppLog.kg.warning("[PodcastSync] progress fetch failed: \(error.localizedDescription)")
        }
        do {
            try context.save()
        } catch {
            AppLog.kg.warning("[PodcastSync] context save failed: \(error.localizedDescription)")
            AppCrashReporting.record(error, context: "podcast.sync.save")
        }
        // Notify frozen-snapshot views (e.g. PodcastEpisodeListView) that the
        // store changed so they can discretely re-read. seriesId is stable
        // across a background upsert, so their `.task(id:)` won't re-fire.
        NotificationCenter.default.post(name: .podcastCatalogDidSync, object: nil)
        return .completed
    }

    @MainActor
    static func upsertSeries(detail: PodcastSeriesDetail, context: ModelContext) {
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
        series.coverImageURL = detail.coverImageURL
        // Server retracted the cover → drop the orphaned local cache so the card
        // degrades back to the procedural cover instead of rendering a stale photo
        // forever (cacheCoverIfNeeded early-returns on nil remote, never cleans up).
        if (detail.coverImageURL ?? "").isEmpty, series.coverImagePath != nil {
            try? FileManager.default.removeItem(at: Self.cachedCoverURL(seriesId: seriesId))
            series.coverImagePath = nil
        }
        series.totalDurationSec = detail.totalDurationSec ?? 0
        series.episodeCount = detail.episodes.count
        series.updatedAt = Date()
        // Resurrect: if server brings a previously-tombstoned series back, clear flag.
        if series.isDeleted { series.isDeleted = false }

        // Single fetch + in-memory index instead of one fetch per episode.
        // Mirrors reconcileLocalState's approach — the old per-episode fetch was
        // O(N) @MainActor SwiftData calls, painful at 1000+ episodes.
        let epDescriptor = FetchDescriptor<PodcastEpisode>(
            predicate: #Predicate { $0.series?.remoteId == seriesId }
        )
        let existingByRemoteId = Dictionary(
            ((try? context.fetch(epDescriptor)) ?? []).map { ($0.remoteId, $0) },
            uniquingKeysWith: { first, _ in first }
        )

        for ep in detail.episodes {
            let epRemoteId = Self.episodeRemoteId(seriesId: detail.id, episodeNumber: ep.episodeNumber)
            let episode: PodcastEpisode

            if let found = existingByRemoteId[epRemoteId] {
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
            episode.inlineSubtitle = ep.subtitleContent
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
        let winner = progressWinner(amongSortedDescending: rows)
        for row in rows where row !== winner {
            context.delete(row)
        }
        return winner
    }

    /// Pick the surviving `PodcastProgress` among duplicates.
    /// - Parameter rows: non-empty, pre-sorted by `updatedAt` descending.
    /// - Returns: newest row; on a tie in `updatedAt`, the one with the larger
    ///   `lastPlayedTime` (closer to the user's true progress).
    private static func progressWinner(
        amongSortedDescending rows: [PodcastProgress]
    ) -> PodcastProgress {
        let newest = rows.first!
        let tied = rows.filter { $0.updatedAt == newest.updatedAt }
        return tied.count > 1
            ? (tied.max(by: { $0.lastPlayedTime < $1.lastPlayedTime }) ?? newest)
            : newest
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

        // 1 + 2: Series tombstone / resurrection.
        // Empty `serverSummaries` is treated as a transient server hiccup and skipped —
        // `/api/podcasts` returns `[]` with HTTP 200 when its S3 index.json is momentarily
        // missing/unreadable (見 podcast.py list_podcasts)，而 syncAll 的 fetch guard 只擋
        // 拋例外、擋不到成功的空回應。若不守衛，空 list → serverSeriesIds 為空 → 整個本地
        // catalog 全被 soft-delete（即書架 podcast 區塊整片消失的根因）。對稱於下方 episode
        // 層的 empty-episodes 守衛。
        if !serverSummaries.isEmpty {
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
        } else {
            AppLog.kg.warning("[PodcastSync] empty server series list — skip series tombstone (avoid mass-delete on transient empty 200)")
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
            let winner = progressWinner(amongSortedDescending: sorted)
            for row in rows where row !== winner {
                context.delete(row)
            }
        }
    }
}
