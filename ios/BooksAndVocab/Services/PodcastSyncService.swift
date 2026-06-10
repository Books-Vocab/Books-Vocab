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
    /// Free-tier preview fields (ep 1 only). Written by `ops/podcast_upload.sh`
    /// / `ops/podcast_preview_backfill.py`; absent on pre-preview series → false/0.
    let previewAvailable: Bool
    let previewDurationSec: Double

    private enum CodingKeys: String, CodingKey {
        case episodeNumber, title, durationSec, audioAvailable, subtitleAvailable, subtitleContent
        case previewAvailable, previewDurationSec
    }

    init(
        episodeNumber: Int,
        title: String,
        durationSec: Double,
        audioAvailable: Bool,
        subtitleAvailable: Bool,
        subtitleContent: String?,
        previewAvailable: Bool = false,
        previewDurationSec: Double = 0
    ) {
        self.episodeNumber = episodeNumber
        self.title = title
        self.durationSec = durationSec
        self.audioAvailable = audioAvailable
        self.subtitleAvailable = subtitleAvailable
        self.subtitleContent = subtitleContent
        self.previewAvailable = previewAvailable
        self.previewDurationSec = previewDurationSec
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
        previewAvailable = try c.decodeIfPresent(Bool.self, forKey: .previewAvailable) ?? false
        previewDurationSec = try c.decodeIfPresent(Double.self, forKey: .previewDurationSec) ?? 0
    }
}

// MARK: - Sync Service

final class PodcastSyncService {
    /// Podcast assets are only hosted on the public backend, so this stays
    /// pinned to `AppURLs.domain` even in debug-local server mode. The single
    /// exception is the UI-test override: an isolated test world must never
    /// sync against the real catalog (reconcile would tombstone seeded series).
    private static var baseURL: String {
        #if DEBUG
        return KGService.uiTestServerURLOverride() ?? AppURLs.domain
        #else
        return AppURLs.domain
        #endif
    }

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
        let (data, _) = try await authedResponseData(from: urlString, kgService: kgService)
        return data
    }

    static func authedResponseData(
        from urlString: String, kgService: any KGServing
    ) async throws -> (Data, URLResponse) {
        guard let url = URL(string: urlString) else {
            throw URLError(.badURL)
        }
        let token = try await kgService.currentAuthToken()
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.addValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        return try await sharedURLSession.data(for: request)
    }

    /// Browse fetch that tolerates an anonymous (guest) caller. The backend
    /// podcast *browse* endpoints (`/api/podcasts`, `/{sid}`, `/{sid}/cover`)
    /// admit guests, so we attach the Bearer token only when one is present —
    /// a logged-out user can still load the catalog/showcase. Playback
    /// endpoints stay on `authedData` (they require a real user). `try?` on the
    /// token: a true guest has none (no side effect); an expired one still
    /// triggers the normal session-invalidation path inside currentAuthToken.
    static func optionallyAuthedData(from urlString: String, kgService: any KGServing) async throws -> Data {
        let (data, _) = try await optionallyAuthedResponseData(from: urlString, kgService: kgService)
        return data
    }

    static func optionallyAuthedResponseData(
        from urlString: String, kgService: any KGServing
    ) async throws -> (Data, URLResponse) {
        guard let url = URL(string: urlString) else {
            throw URLError(.badURL)
        }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        if let token = try? await kgService.currentAuthToken() {
            request.addValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        return try await sharedURLSession.data(for: request)
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

    static func cachedCoverURL(seriesId: String, coverImageURL: String?) -> URL {
        guard let token = coverCacheToken(from: coverImageURL) else {
            return cachedCoverURL(seriesId: seriesId)
        }
        return Self.coversRoot().appendingPathComponent("\(seriesId)_\(token).png")
    }

    static func coverCacheToken(from coverImageURL: String?) -> String? {
        guard let coverImageURL, !coverImageURL.isEmpty else { return nil }
        let value: String?
        if let components = URLComponents(string: coverImageURL),
           let queryValue = components.queryItems?.first(where: { $0.name == "v" })?.value {
            value = queryValue
        } else {
            value = nil
        }
        guard let value else { return nil }
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "_-"))
        let sanitized = String(value.unicodeScalars.filter { allowed.contains($0) })
        return sanitized.isEmpty ? nil : sanitized
    }

    static func removeCachedCover(seriesId: String, path: String? = nil) {
        let fm = FileManager.default
        if let path {
            try? fm.removeItem(atPath: path)
        }
        try? fm.removeItem(at: cachedCoverURL(seriesId: seriesId))
    }

    static func isValidCoverResponse(data: Data, response: URLResponse) -> Bool {
        guard let http = response as? HTTPURLResponse,
              (200..<300).contains(http.statusCode),
              (http.mimeType ?? "").lowercased() == "image/png",
              data.count >= 8 else { return false }
        return Array(data.prefix(8)) == [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]
    }

    static func cacheCovers(
        seriesIds: [String],
        maxConcurrent: Int = 3,
        operation: @escaping (String) async -> Void
    ) async {
        guard !seriesIds.isEmpty else { return }
        let limit = max(1, min(maxConcurrent, seriesIds.count))
        await withTaskGroup(of: Void.self) { group in
            var iterator = seriesIds.makeIterator()
            for _ in 0..<limit {
                if let seriesId = iterator.next() {
                    group.addTask { await operation(seriesId) }
                }
            }
            while await group.next() != nil {
                if let seriesId = iterator.next() {
                    group.addTask { await operation(seriesId) }
                }
            }
        }
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

        let cacheURL = Self.cachedCoverURL(seriesId: seriesId, coverImageURL: remote)
        // Already cached + on disk → reuse (a series cover is stable).
        if series.coverImagePath == cacheURL.path,
           FileManager.default.fileExists(atPath: cacheURL.path) {
            return
        }
        let oldPath = series.coverImagePath

        let urlString = remote.hasPrefix("http") ? remote : "\(baseURL)\(remote)"
        do {
            let (data, response) = try await optionallyAuthedResponseData(from: urlString, kgService: kgService)
            guard isValidCoverResponse(data: data, response: response) else {
                AppLog.kg.warning("[PodcastSync] cover for \(seriesId) not a PNG; skipped")
                return
            }
            try FileManager.default.createDirectory(
                at: Self.coversRoot(), withIntermediateDirectories: true
            )
            try data.write(to: cacheURL, options: .atomic)
            if let oldPath, oldPath != cacheURL.path {
                try? FileManager.default.removeItem(atPath: oldPath)
            }
            series.coverImagePath = cacheURL.path
        } catch is CancellationError {
            return
        } catch {
            AppLog.kg.warning("[PodcastSync] cover fetch failed for \(seriesId): \(error.localizedDescription)")
        }
    }

    func fetchSeriesList() async throws -> [PodcastSeriesSummary] {
        // Browse is open to guests — attach a token only if signed in.
        let data = try await Self.optionallyAuthedData(from: "\(Self.baseURL)/api/podcasts", kgService: kgService)
        return try JSONDecoder().decode([PodcastSeriesSummary].self, from: data)
    }

    func fetchSeriesDetail(seriesId: String) async throws -> PodcastSeriesDetail {
        let data = try await Self.optionallyAuthedData(from: "\(Self.baseURL)/api/podcasts/\(seriesId)", kgService: kgService)
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
        var coverSeriesIds: [String] = []
        for summary in summaries {
            do {
                let detail = try await fetchSeriesDetail(seriesId: summary.id)
                details[summary.id] = detail
                Self.upsertSeries(detail: detail, context: context)
                if !(detail.coverImageURL ?? "").isEmpty {
                    coverSeriesIds.append(summary.id)
                }
            } catch {
                AppLog.kg.warning("[PodcastSync] detail fetch failed for \(summary.id): \(error.localizedDescription)")
                if !(error is CancellationError) {
                    AppCrashReporting.record(error, context: "podcast.sync.detail")
                }
            }
        }
        // Best-effort remote-cover downloads into the local cache. Bounded
        // concurrency avoids first-sync waterfall latency without stampeding
        // the backend when the catalog grows.
        await Self.cacheCovers(seriesIds: coverSeriesIds) { seriesId in
            await Self.cacheCoverIfNeeded(seriesId: seriesId, context: context, kgService: self.kgService)
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
            Self.removeCachedCover(seriesId: seriesId, path: series.coverImagePath)
            series.coverImagePath = nil
        }
        series.totalDurationSec = detail.totalDurationSec ?? 0
        series.episodeCount = detail.episodes.count
        series.updatedAt = Date()
        // Resurrect: if server brings a previously-tombstoned series back, clear flag.
        if series.isSoftDeleted { series.isSoftDeleted = false }

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
            episode.previewAvailable = ep.previewAvailable
            episode.previewDurationSec = ep.previewDurationSec
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
        guard let rows = try? context.fetch(descriptor),
              let winner = progressWinner(amongSortedDescending: rows) else {
            return nil
        }
        for row in rows where row !== winner {
            context.delete(row)
        }
        return winner
    }

    /// Pick the surviving `PodcastProgress` among duplicates.
    /// - Parameter rows: pre-sorted by `updatedAt` descending.
    /// - Returns: newest row (nil when `rows` is empty); on a tie in
    ///   `updatedAt`, the one with the larger `lastPlayedTime` (closer to the
    ///   user's true progress).
    private static func progressWinner(
        amongSortedDescending rows: [PodcastProgress]
    ) -> PodcastProgress? {
        guard let newest = rows.first else { return nil }
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
    /// 1. Series tombstone: local series not in `serverSummaries` → soft-delete (`isSoftDeleted = true`).
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
                if onServer && series.isSoftDeleted {
                    series.isSoftDeleted = false
                    series.updatedAt = Date()
                } else if !onServer && !series.isSoftDeleted {
                    series.isSoftDeleted = true
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
                // Prevent orphan MP3s from accumulating disk space.
                if let path = ep.localAudioPath {
                    try? FileManager.default.removeItem(atPath: path)
                }
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
            guard let winner = progressWinner(amongSortedDescending: sorted) else { continue }
            for row in rows where row !== winner {
                context.delete(row)
            }
        }
    }
}
