import Foundation
import SwiftData

// MARK: - API Models

/// One row returned by ``GET /api/podcasts/progress`` or
/// ``GET /api/podcasts/{series}/{ep}/progress``.
struct PodcastRemoteProgressItem: Codable, Equatable {
    let seriesId: String
    let epNum: Int
    let positionSec: Double
    let durationSec: Double
    /// ISO8601 UTC — the backend canonicalises to ``+00:00`` so direct
    /// string comparison is valid as a last-write-wins primary key.
    let updatedAt: String

    enum CodingKeys: String, CodingKey {
        case seriesId = "series_id"
        case epNum = "ep_num"
        case positionSec = "position_sec"
        case durationSec = "duration_sec"
        case updatedAt = "updated_at"
    }
}

private struct _ProgressListResponse: Codable {
    let items: [PodcastRemoteProgressItem]
}

// MARK: - Throttle state

/// Tracks the last successful push so the player loop can decide whether to
/// send another one. Used by ``PodcastPlayerView`` to gate writes triggered
/// by the high-frequency ``onChange(of: currentTime)`` callback.
///
/// Rules:
/// * First write of the session → always allow.
/// * Subsequent ticks → require either ≥ 10s elapsed OR ≥ 5% position jump
///   relative to duration (so manual scrubs flush immediately).
/// * ``.pause`` and ``.episodeSwitch`` reasons bypass the gates entirely —
///   those are user-visible state transitions and must be durable.
/// * ``duration == 0`` (audio not yet loaded) blocks tick writes; the
///   pause / episodeSwitch path is unaffected.
struct PodcastProgressPushState {
    enum Reason {
        case tick
        case pause
        case episodeSwitch
    }

    private var lastPushedAt: Date?
    private var lastPushedPosition: Double?

    static let minInterval: TimeInterval = 10
    static let minPercentJump: Double = 0.05

    mutating func shouldPush(
        position: Double,
        duration: Double,
        now: Date,
        reason: Reason
    ) -> Bool {
        switch reason {
        case .pause, .episodeSwitch:
            lastPushedAt = now
            lastPushedPosition = position
            return true
        case .tick:
            break
        }

        if duration <= 0 { return false }

        guard let lastAt = lastPushedAt, let lastPos = lastPushedPosition else {
            lastPushedAt = now
            lastPushedPosition = position
            return true
        }

        let elapsed = now.timeIntervalSince(lastAt)
        let percentJump = abs(position - lastPos) / duration

        if elapsed >= Self.minInterval || percentJump >= Self.minPercentJump {
            lastPushedAt = now
            lastPushedPosition = position
            return true
        }
        return false
    }
}

// MARK: - Service extensions

extension PodcastSyncService {
    private static var progressBaseURL: String { AppURLs.domain }

    /// Decompose ``{seriesId}_ep_{NN}`` back into its components.
    /// Returns ``nil`` when the suffix marker (`_ep_`) is missing or the
    /// trailing segment isn't a positive integer.
    static func parseEpisodeRemoteId(_ remoteId: String) -> (seriesId: String, episodeNumber: Int)? {
        guard let range = remoteId.range(of: "_ep_", options: .backwards) else {
            return nil
        }
        let seriesId = String(remoteId[..<range.lowerBound])
        let epStr = String(remoteId[range.upperBound...])
        guard !seriesId.isEmpty,
              let ep = Int(epStr),
              ep >= 1 else {
            return nil
        }
        return (seriesId, ep)
    }

    /// Push a single episode's progress to the backend (last-write-wins).
    func pushProgress(
        seriesId: String,
        episodeNumber: Int,
        positionSec: Double,
        durationSec: Double,
        updatedAt: Date
    ) async throws {
        let url = URL(string: "\(Self.progressBaseURL)/api/podcasts/\(seriesId)/\(episodeNumber)/progress")!
        let token = try await kgService.currentAuthToken()
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.addValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.addValue("application/json", forHTTPHeaderField: "Content-Type")
        let payload: [String: Any] = [
            "position_sec": positionSec,
            "duration_sec": durationSec,
            "updated_at": ISO8601DateFormatter.podcastProgress.string(from: updatedAt),
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: payload)
        let (_, response) = try await URLSession.shared.data(for: request)
        if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            throw URLError(.badServerResponse)
        }
    }

    /// Pull every progress row for the authenticated user.
    func fetchAllProgress() async throws -> [PodcastRemoteProgressItem] {
        let data = try await Self.authedData(
            from: "\(Self.progressBaseURL)/api/podcasts/progress",
            kgService: kgService
        )
        let resp = try JSONDecoder().decode(_ProgressListResponse.self, from: data)
        return resp.items
    }

    // MARK: - Merge

    /// Apply remote rows onto local SwiftData under last-write-wins.
    ///
    /// For each parseable remote item:
    /// 1. Collapse any local duplicates for that episode (CloudKit drift).
    /// 2. If no local row exists, insert one from the remote payload.
    /// 3. Otherwise, compare ``updatedAt`` instants and keep the newer side.
    @MainActor
    static func mergeRemoteProgress(
        remote: [PodcastRemoteProgressItem],
        context: ModelContext
    ) {
        let formatter = ISO8601DateFormatter.podcastProgress
        for item in remote {
            guard !item.seriesId.isEmpty, item.epNum >= 1 else { continue }
            guard let remoteUpdatedAt = formatter.date(from: item.updatedAt) else {
                continue
            }
            let episodeRemoteId = episodeRemoteId(seriesId: item.seriesId, episodeNumber: item.epNum)

            let surviving = sanitizeProgressDuplicates(for: episodeRemoteId, context: context)

            if let local = surviving {
                if remoteUpdatedAt > local.updatedAt {
                    local.lastPlayedTime = item.positionSec
                    local.updatedAt = remoteUpdatedAt
                    if item.durationSec > 0 {
                        local.completed = item.positionSec >= item.durationSec - 1
                    }
                }
            } else {
                let progress = PodcastProgress(
                    episodeRemoteId: episodeRemoteId,
                    lastPlayedTime: item.positionSec,
                    completed: item.durationSec > 0 && item.positionSec >= item.durationSec - 1
                )
                progress.updatedAt = remoteUpdatedAt
                context.insert(progress)
            }
        }
    }
}

// MARK: - Date formatter

private extension ISO8601DateFormatter {
    /// Matches the backend's canonical form (``+00:00`` offset, no fractional
    /// seconds). Reused for both encode (push) and decode (merge).
    static let podcastProgress: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()
}
