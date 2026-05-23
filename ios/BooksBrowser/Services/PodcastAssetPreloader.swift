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
/// from being torn down before the player picks it up. Self-evicts expired
/// entries on every `preload` call; no timer needed.
@MainActor
final class PodcastAssetPreloader {
    static let shared = PodcastAssetPreloader()

    private struct Entry {
        let asset: AVURLAsset
        let task: Task<Void, Never>
        let expires: Date
    }

    private var pending: [String: Entry] = [:]
    private let ttl: TimeInterval = 60

    private init() {}

    /// Fire-and-forget warmup. Safe to call repeatedly for the same URL —
    /// in-flight or recently-warmed entries are reused.
    func preload(url: URL, headers: [String: String] = [:]) {
        let key = url.absoluteString
        let now = Date()
        evictExpired(now: now)
        if pending[key] != nil { return }

        // Mirror engine settings: skip precise-duration probe (we only need
        // connection warmup, not metadata accuracy) and attach auth headers
        // so the Range request actually succeeds and primes the auth'd path.
        var opts: [String: Any] = [
            AVURLAssetPreferPreciseDurationAndTimingKey: false
        ]
        if !headers.isEmpty {
            opts["AVURLAssetHTTPHeaderFieldsKey"] = headers
        }
        let asset = AVURLAsset(url: url, options: opts)
        let task = Task { [weak self] in
            _ = try? await asset.load(.isPlayable)
            // Once isPlayable resolves the handshake is done; we no longer need
            // to hold the asset proactively but the 60s TTL keeps it alive for
            // the navigation transition. Self-cleanup happens on next preload.
            _ = self
        }
        pending[key] = Entry(asset: asset, task: task, expires: now.addingTimeInterval(ttl))
    }

    /// Drop an entry early — call when navigation is cancelled so we don't
    /// hold the connection longer than needed.
    func cancel(url: URL) {
        let key = url.absoluteString
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
}
