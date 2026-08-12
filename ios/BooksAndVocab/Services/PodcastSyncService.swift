import Foundation
import SwiftData

// MARK: - Podcast sync facade

/// The public sync type remains source-compatible while its implementation is
/// kept in `PodcastSyncServiceCore.swift`.  Network, cover-file, and reconcile
/// seams below are intentionally small value types so each failure policy can
/// be tested without constructing the full sync service.
// The concrete `PodcastSyncService` declaration lives in the core file; this
// facade file owns the extracted seams and their contracts.

struct PodcastCatalogTransport {
    typealias Request = (URLRequest) async throws -> (Data, URLResponse)

    let request: Request
    let basePath: String

    static func live(session: URLSession = sharedURLSession) -> Self {
        Self { request in
            try await session.data(for: request)
        }
    }

    init(
        basePath: String = "/api/podcasts",
        request: @escaping Request
    ) {
        self.basePath = basePath
        self.request = request
    }

    func send(_ request: URLRequest) async throws -> (Data, URLResponse) {
        try await self.request(request)
    }

    func data(from urlString: String, bearerToken: String?) async throws -> Data {
        guard let url = URL(string: urlString) else { throw URLError(.badURL) }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        if let bearerToken {
            request.addValue("Bearer \(bearerToken)", forHTTPHeaderField: "Authorization")
        }
        let (data, response) = try await send(request)
        if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            throw URLError(.badServerResponse)
        }
        return data
    }

    func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        try JSONDecoder().decode(type, from: data)
    }
}

struct PodcastCoverCaching {
    private static let pngSignature: [UInt8] = [
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A
    ]

    static func isValidResponse(data: Data, response: URLResponse) -> Bool {
        guard let http = response as? HTTPURLResponse,
              (200..<300).contains(http.statusCode),
              (http.mimeType ?? "").lowercased() == "image/png",
              data.count >= pngSignature.count else { return false }
        return Array(data.prefix(pngSignature.count)) == pngSignature
    }

    static func write(_ data: Data, to path: URL) throws {
        try FileManager.default.createDirectory(
            at: path.deletingLastPathComponent(), withIntermediateDirectories: true
        )
        try data.write(to: path, options: .atomic)
    }

    static func read(from path: URL) throws -> Data? {
        guard FileManager.default.fileExists(atPath: path.path) else { return nil }
        return try Data(contentsOf: path)
    }

    static func remove(at path: URL) throws {
        guard FileManager.default.fileExists(atPath: path.path) else { return }
        try FileManager.default.removeItem(at: path)
    }

    static func coversRoot() -> URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("podcast-covers", isDirectory: true)
    }

    static func cachedCoverURL(seriesId: String, coverImageURL: String? = nil) -> URL {
        let suffix = coverCacheToken(from: coverImageURL).map { "_\($0)" } ?? ""
        return coversRoot().appendingPathComponent("\(seriesId)\(suffix).png")
    }

    static func coverCacheToken(from coverImageURL: String?) -> String? {
        guard let coverImageURL, !coverImageURL.isEmpty,
              let components = URLComponents(string: coverImageURL),
              let value = components.queryItems?.first(where: { $0.name == "v" })?.value
        else { return nil }
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "_-"))
        let sanitized = String(value.unicodeScalars.filter { allowed.contains($0) })
        return sanitized.isEmpty ? nil : sanitized
    }

    static func removeCachedCover(seriesId: String, path: String? = nil) {
        if let path { try? remove(at: URL(fileURLWithPath: path)) }
        try? remove(at: cachedCoverURL(seriesId: seriesId))
    }

    static func cacheCovers(
        seriesIds: [String], maxConcurrent: Int = 3,
        operation: @escaping (String) async -> Void
    ) async {
        guard !seriesIds.isEmpty else { return }
        let limit = max(1, min(maxConcurrent, seriesIds.count))
        await withTaskGroup(of: Void.self) { group in
            var iterator = seriesIds.makeIterator()
            for _ in 0..<limit {
                if let seriesId = iterator.next() { group.addTask { await operation(seriesId) } }
            }
            while await group.next() != nil {
                if let seriesId = iterator.next() { group.addTask { await operation(seriesId) } }
            }
        }
    }

    @MainActor
    static func cacheCoverIfNeeded(
        seriesId: String, context: ModelContext, kgService: any KGServing,
        baseURL: String, fetch: @escaping (String) async throws -> (Data, URLResponse)
    ) async {
        let descriptor = FetchDescriptor<PodcastSeries>(predicate: #Predicate { $0.remoteId == seriesId })
        guard let series = try? context.fetch(descriptor).first,
              let remote = series.coverImageURL, !remote.isEmpty else { return }
        let cacheURL = cachedCoverURL(seriesId: seriesId, coverImageURL: remote)
        if series.coverImagePath == cacheURL.path, (try? read(from: cacheURL)) != nil { return }
        let oldPath = series.coverImagePath
        let urlString = remote.hasPrefix("http") ? remote : "\(baseURL)\(remote)"
        do {
            let (data, response) = try await fetch(urlString)
            guard isValidResponse(data: data, response: response) else {
                AppLog.kg.warning("[PodcastSync] cover for \(seriesId) not a PNG; skipped")
                return
            }
            try write(data, to: cacheURL)
            if let oldPath, oldPath != cacheURL.path { try? remove(at: URL(fileURLWithPath: oldPath)) }
            series.coverImagePath = cacheURL.path
        } catch is CancellationError {
            return
        } catch {
            AppLog.kg.warning("[PodcastSync] cover fetch failed for \(seriesId): \(error.localizedDescription)")
        }
    }
}

@MainActor
struct PodcastCatalogReconciler {
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
        guard let rows = try? context.fetch(descriptor), let newest = rows.first else {
            return nil
        }
        let tied = rows.filter { $0.updatedAt == newest.updatedAt }
        let winner = tied.max(by: { $0.lastPlayedTime < $1.lastPlayedTime }) ?? newest
        for row in rows where row !== winner { context.delete(row) }
        return winner
    }

    /// Reconcile only authoritative, non-empty catalog responses for series
    /// tombstones. Episode cleanup and progress dedup remain active for fetched
    /// details even when the list response is empty.
    static func reconcile(
        serverSummaries: [PodcastSeriesSummary],
        fetchedDetails: [String: PodcastSeriesDetail],
        context: ModelContext
    ) {
        let ids = Set(serverSummaries.map(\.id))
        let allSeries = (try? context.fetch(FetchDescriptor<PodcastSeries>())) ?? []
        if !serverSummaries.isEmpty {
            for series in allSeries {
                let shouldDelete = !ids.contains(series.remoteId)
                if series.isSoftDeleted != shouldDelete {
                    series.isSoftDeleted = shouldDelete
                    series.updatedAt = Date()
                }
            }
        }

        for (seriesId, detail) in fetchedDetails where !detail.episodes.isEmpty {
            let serverIds = Set(detail.episodes.map {
                PodcastSyncService.episodeRemoteId(seriesId: seriesId, episodeNumber: $0.episodeNumber)
            })
            let descriptor = FetchDescriptor<PodcastEpisode>(
                predicate: #Predicate { $0.series?.remoteId == seriesId }
            )
            let local = (try? context.fetch(descriptor)) ?? []
            for episode in local where !serverIds.contains(episode.remoteId) {
                if let path = episode.localAudioPath {
                    try? FileManager.default.removeItem(atPath: path)
                }
                context.delete(episode)
            }
        }

        let liveIds = Set(((try? context.fetch(FetchDescriptor<PodcastEpisode>())) ?? []).map(\.remoteId))
        let progress = (try? context.fetch(FetchDescriptor<PodcastProgress>())) ?? []
        var grouped: [String: [PodcastProgress]] = [:]
        for row in progress {
            guard liveIds.contains(row.episodeRemoteId) else {
                context.delete(row)
                continue
            }
            grouped[row.episodeRemoteId, default: []].append(row)
        }
        for rows in grouped.values where rows.count > 1 {
            guard let winner = rows.max(by: {
                if $0.updatedAt == $1.updatedAt { return $0.lastPlayedTime < $1.lastPlayedTime }
                return $0.updatedAt < $1.updatedAt
            }) else { continue }
            for row in rows where row !== winner { context.delete(row) }
        }
    }
}
