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

struct PodcastSeriesSummary: Codable, Sendable {
    let id: String
    let title: String
    let author: String?
    let hostNames: [String]?
    let color: String?
    let coverPattern: String?
    let coverImageURL: String?
    let totalDurationSec: Double?
    let episodeCount: Int?
    /// 伺服器的內容指紋。**一直都在清單裡**，只是這個型別以前沒解它。
    ///
    /// `index.json` 是 `metadata.json` 的機械式投影（去掉 episodes、補上
    /// episodeCount，見 `ops/podcast_upload.sh`），所以清單天生帶著和 detail
    /// 一樣的 `updatedAt`。2026-08-06 對生產驗過：四個 series 全部有值。
    /// 這一個欄位就是「不必抓 detail 也知道它沒變」的全部依據。
    let updatedAt: String?
}

struct PodcastSeriesDetail: Codable, Sendable {
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

struct PodcastEpisodeDetail: Codable, Sendable {
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
    static func authedData(from urlString: String, kgService: any AuthTokenProviding) async throws -> Data {
        let (data, _) = try await authedResponseData(from: urlString, kgService: kgService)
        return data
    }

    static func authedResponseData(
        from urlString: String, kgService: any AuthTokenProviding
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
    /// endpoints stay on `authedData` (they require a real user). An expired
    /// token is treated as absent without invalidating the session.
    static func optionallyAuthedData(
        from urlString: String,
        kgService: any KGServing,
        session: URLSession = sharedURLSession
    ) async throws -> Data {
        let (data, _) = try await optionallyAuthedResponseData(
            from: urlString, kgService: kgService, session: session
        )
        return data
    }

    static func optionallyAuthedResponseData(
        from urlString: String,
        kgService: any KGServing,
        session: URLSession = sharedURLSession
    ) async throws -> (Data, URLResponse) {
        guard let url = URL(string: urlString) else {
            throw URLError(.badURL)
        }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        if let token = await kgService.authTokenWithoutInvalidation() {
            request.addValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        return try await session.data(for: request)
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
        // 只抓「內容指紋變了」的 series，而且併發抓。
        //
        // 舊版對每個 series 各發一次請求、序列等待：2026-08-06 生產量測 7.55s 的
        // 整輪同步裡有 6.08s 在這個迴圈，而四個 series 的資料總量只有約 7 KB。
        // 貴的是往返次數，不是位元組——每多一個 series，每次同步就多約 1.5 秒。
        //
        // **刻意不走「把 detail 內嵌進 list」那條路。** `episodes[].subtitleContent`
        // 是整份 inline SRT（實測 165–212 KB／集，8 集的 metadata.json ≈ 1.4 MB），
        // 而 `app_middleware.py` 沒掛 GZipMiddleware。內嵌會把 7 KB 的回應變成數 MB，
        // 用頻寬換往返，在行動網路上是虧的。
        //
        // 穩態成本因此是 **1 趟**（只有清單），不是 1+N。
        let localIndex = Self.localSeriesIndex(context: context)
        let stale = summaries.filter {
            Self.needsDetailFetch(summary: $0, local: localIndex[$0.id])
        }
        // 無條件印。舊版包在 `if stale.count < summaries.count` 裡＝「只有健康時才
        // 說話」：退回「全部都得抓」那一輪反而零輸出，方向正好是反的。
        AppLog.kg.info("[PodcastSync] detail fetch total=\(summaries.count) stale=\(stale.count) skipped=\(summaries.count - stale.count)")
        let fetched = await Self.fetchDetailsConcurrently(seriesIds: stale.map(\.id)) { [kgService] seriesId in
            do {
                return try await PodcastSyncService(kgService: kgService).fetchSeriesDetail(seriesId: seriesId)
            } catch {
                AppLog.kg.warning("[PodcastSync] detail fetch failed for \(seriesId): \(error.localizedDescription)")
                if !(error is CancellationError) {
                    AppCrashReporting.record(error, context: "podcast.sync.detail")
                }
                return nil
            }
        }
        // upsert 留在 MainActor 上依序做（SwiftData 契約），只有網路那段併發。
        var details: [String: PodcastSeriesDetail] = [:]
        for summary in summaries {
            guard let detail = fetched[summary.id] else { continue }
            details[summary.id] = detail
            Self.upsertSeries(detail: detail, context: context)
        }
        // 封面改由**清單**驅動而非只看這輪抓到的 detail：跳過的 series 也該有機會
        // 補上它上次沒下載成功的封面。已快取者 `cacheCoverIfNeeded` 直接早退，
        // 不產生任何網路請求。
        let coverSeriesIds = summaries
            .filter { !($0.coverImageURL ?? "").isEmpty }
            .map(\.id)
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

    // MARK: - 降趟：只抓變更過的 series

    @MainActor
    static func localSeriesIndex(context: ModelContext) -> [String: PodcastSeries] {
        let all = (try? context.fetch(FetchDescriptor<PodcastSeries>())) ?? []
        return Dictionary(all.map { ($0.remoteId, $0) }, uniquingKeysWith: { first, _ in first })
    }

    /// 內容指紋。**不是只有 `updatedAt`。**
    ///
    /// 發布工具會在不 bump `updatedAt` 的前提下改動內容：
    /// `ops/podcast_cover_publish.py:109` 換掉 `coverImageURL` 並重建 `index.json`，
    /// 但明文寫著「updatedAt is deliberately NOT bumped」。只比 `updatedAt` 的話，
    /// 那個新封面永遠不會落到已安裝的裝置上——而 `cacheCoverIfNeeded` 讀的是**本機**
    /// 那一列的 `coverImageURL`，所以連「封面清單改由 summary 驅動」都救不了它。
    ///
    /// 因此指紋涵蓋 `index.json` 會投影、而 `upsertSeries` 會寫下的每個欄位。多比
    /// 幾個字串的成本是零，漏比一個欄位的成本是一個永遠修不好的畫面。
    /// 指紋涵蓋的欄位 = **`upsertSeries` 會寫進 `PodcastSeries` 的每一個伺服器欄位**。
    /// 那個對應是刻意的：任何在指紋外的欄位，只要發布工具改了它而不 bump
    /// `updatedAt`，就會永久不同步。`hostNames` / `color` / `coverPattern` 今天
    /// 沒有工具會那樣改，但把它們留在外面就是在賭下一支工具不會。
    nonisolated static func fingerprint(
        updatedAt: String?,
        coverImageURL: String?,
        title: String,
        totalDurationSec: Double?,
        episodeCount: Int?,
        hostNames: [String]?,
        color: String?,
        coverPattern: String?
    ) -> String {
        // U+001F unit separator：不會出現在任何一個欄位裡，所以不同的欄位組合
        // 不可能拼出同一個字串。`String(Double)` 走 `Double.description`，恆為
        // `.` 小數點、與 locale 無關——用 `"\(value)"` 進格式化路徑才會有事。
        [
            updatedAt ?? "",
            coverImageURL ?? "",
            title,
            totalDurationSec.map { String($0) } ?? "",
            episodeCount.map(String.init) ?? "",
            (hostNames ?? []).joined(separator: "\u{1E}"),
            color ?? "",
            coverPattern ?? ""
        ].joined(separator: "\u{1F}")
    }

    nonisolated static func fingerprint(of summary: PodcastSeriesSummary) -> String {
        fingerprint(
            updatedAt: summary.updatedAt, coverImageURL: summary.coverImageURL,
            title: summary.title, totalDurationSec: summary.totalDurationSec,
            episodeCount: summary.episodeCount, hostNames: summary.hostNames,
            color: summary.color, coverPattern: summary.coverPattern
        )
    }

    nonisolated static func fingerprint(of detail: PodcastSeriesDetail) -> String {
        fingerprint(
            updatedAt: detail.updatedAt, coverImageURL: detail.coverImageURL,
            title: detail.title, totalDurationSec: detail.totalDurationSec,
            episodeCount: detail.episodes.count, hostNames: detail.hostNames,
            color: detail.color, coverPattern: detail.coverPattern
        )
    }

    /// 這個 series 需不需要重抓 detail。
    ///
    /// 每一條 `true` 都是「省下這一趟會出錯」的具體情況，不是保守而已：
    /// - **沒見過** → 本機根本沒有 episodes。
    /// - **被 tombstone 過** → 復活時要把 episodes 拿回來。
    /// - **伺服器沒給 `updatedAt`** → 指紋失去它最主要的成分，不省。
    /// - **指紋不同** → 內容真的變了（含只換封面那種不 bump 時戳的變更）。
    /// - **episode 數對不上** → 本機是半套。這條是完整性檢查而不是快取檢查：
    ///   指紋相同但本機只有 3 集而伺服器說 8 集時，靠指紋就會永遠卡在半套狀態。
    ///
    /// **已知盲點（需要工具側配合，不是這裡能解的）**：若發布工具改了 episode
    /// *內部*的欄位（例如 `previewAvailable`）卻既不 bump `updatedAt` 也不重建
    /// `index.json`，清單上不會有任何差異，客戶端無從察覺。
    /// `ops/podcast_preview_backfill.py` 本來就是這樣，已在同一批改成會 bump。
    @MainActor
    static func needsDetailFetch(summary: PodcastSeriesSummary, local: PodcastSeries?) -> Bool {
        guard let local else { return true }
        if local.isSoftDeleted { return true }
        guard let stamp = summary.updatedAt, !stamp.isEmpty else { return true }
        guard local.remoteFingerprint == fingerprint(of: summary) else { return true }
        if let expected = summary.episodeCount, local.episodes.count != expected { return true }
        return false
    }

    /// 併發抓 detail，滑動視窗上限與 `cacheCovers` 同一套形狀（同檔 :243）——
    /// 不重造，也不無上限併發（目錄長大時會變成對後端的 stampede）。
    static func fetchDetailsConcurrently(
        seriesIds: [String],
        maxConcurrent: Int = 3,
        fetch: @escaping @Sendable (String) async -> PodcastSeriesDetail?
    ) async -> [String: PodcastSeriesDetail] {
        guard !seriesIds.isEmpty else { return [:] }
        let limit = max(1, min(maxConcurrent, seriesIds.count))
        var results: [String: PodcastSeriesDetail] = [:]
        await withTaskGroup(of: (String, PodcastSeriesDetail?).self) { group in
            var iterator = seriesIds.makeIterator()
            for _ in 0..<limit {
                if let seriesId = iterator.next() {
                    group.addTask { (seriesId, await fetch(seriesId)) }
                }
            }
            while let (seriesId, detail) = await group.next() {
                if let detail { results[seriesId] = detail }
                if let next = iterator.next() {
                    group.addTask { (next, await fetch(next)) }
                }
            }
        }
        return results
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
        // 內容指紋。這整支是同步的 `@MainActor`，中間沒有 suspension point，
        // 所以「指紋落地但 episodes 沒落地」今天不可能發生。**但如果之後有人把
        // episode upsert 拆成 async，這行就必須移到最後**——否則會永久跳過重抓。
        // `needsDetailFetch` 的 episode 數檢查是那時的第二道防線。
        series.remoteFingerprint = Self.fingerprint(of: detail)
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
