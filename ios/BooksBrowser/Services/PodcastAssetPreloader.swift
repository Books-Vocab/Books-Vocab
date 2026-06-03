import Foundation
import AVFoundation

/// Warms AVFoundation's HTTP/2 connection pool for an upcoming podcast load.
///
/// Tap-on-row → navigation push takes ~300ms. Firing `AVURLAsset.load(.isPlayable)`
/// in that window lets AVFoundation complete DNS → TLS → TCP → first auth'd Range
/// before the real `PodcastAudioEngine.loadAudio` runs in the player view. The
/// kernel TCP cache + AVFoundation's own HTTP/2 reuse mean the second asset
/// (created by the engine) skips the handshake — typical savings 200~500ms on
/// cold network, more on mobile carrier with high RTT.
///
/// Holds a strong asset reference for 60s to keep the underlying connection
/// alive. Failed loads (401, network down) evict immediately so retries don't
/// silently no-op. Bounded by `maxEntries` LRU so power users tapping many
/// rows can't accumulate handles.
@MainActor
final class PodcastAssetPreloader {
    static let shared = PodcastAssetPreloader()

    private struct Entry {
        let asset: AVURLAsset
        let task: Task<Void, Never>
        let expires: Date
        let inserted: Date
    }

    private var pending: [String: Entry] = [:]
    private let ttl: TimeInterval = 60
    private let maxEntries = 5

    private init() {}

    /// Fire-and-forget warmup. Safe to call repeatedly for the same URL —
    /// in-flight or recently-warmed entries are reused. Failed entries are
    /// evicted immediately so a subsequent call retries.
    func preload(url: URL, headers: [String: String] = [:]) {
        let key = url.absoluteString
        let now = Date()
        evictExpired(now: now)
        if pending[key] != nil { return }
        evictOldestIfFull()

        var opts: [String: Any] = [
            AVURLAssetPreferPreciseDurationAndTimingKey: false
        ]
        if !headers.isEmpty {
            opts["AVURLAssetHTTPHeaderFieldsKey"] = headers
        }
        let asset = AVURLAsset(url: url, options: opts)
        let task = Task { [weak self] in
            let ok: Bool
            do {
                ok = try await asset.load(.isPlayable)
            } catch {
                ok = false
            }
            // Evict on failure so the next tap retries instead of hitting a
            // stale dead entry for the rest of the TTL window.
            if !ok || Task.isCancelled {
                self?.evict(key: key)
            }
        }
        pending[key] = Entry(
            asset: asset,
            task: task,
            expires: now.addingTimeInterval(ttl),
            inserted: now
        )
    }

    private func evict(key: String) {
        pending[key]?.task.cancel()
        pending.removeValue(forKey: key)
    }

    private func evictExpired(now: Date) {
        pending = pending.filter { entry in
            if entry.value.expires > now { return true }
            entry.value.task.cancel()
            return false
        }
    }

    private func evictOldestIfFull() {
        guard pending.count >= maxEntries else { return }
        guard let oldest = pending.min(by: { $0.value.inserted < $1.value.inserted }) else { return }
        oldest.value.task.cancel()
        pending.removeValue(forKey: oldest.key)
    }
}
