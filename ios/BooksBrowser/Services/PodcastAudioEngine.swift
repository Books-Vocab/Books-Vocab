import Foundation
import AVFoundation

/// Streams podcast audio via AVPlayer (HTTP Range requests under the hood).
/// Replaces the previous AVAudioEngine implementation which required the full file
/// to be downloaded before playback could begin.
final class PodcastAudioEngine: NSObject {
    private var player: AVPlayer?
    private var playerItem: AVPlayerItem?
    private var timeObserver: Any?
    private var endObserver: NSObjectProtocol?
    private var failObserver: NSObjectProtocol?
    private var stallObserver: NSObjectProtocol?
    private var statusObserver: NSKeyValueObservation?
    // Incremented on every loadAudio; async tasks capture + compare to bail out
    // when a later load has superseded them (prevents stale duration / ready signals).
    private var loadGeneration: UInt64 = 0

    private(set) var playbackRate: Float = 1.0
    private(set) var duration: TimeInterval = 0

    var onTimeUpdate: ((TimeInterval) -> Void)?
    var onPlaybackFinished: (() -> Void)?
    var onDurationLoaded: ((TimeInterval) -> Void)?
    var onReadyToPlay: (() -> Void)?
    var onLoadFailed: ((String) -> Void)?

    static let rateSteps: [Float] = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]

    static func nextRate(after current: Float) -> Float {
        guard let idx = rateSteps.firstIndex(where: { abs($0 - current) < 0.01 }) else {
            return 1.0
        }
        return rateSteps[(idx + 1) % rateSteps.count]
    }

    deinit {
        removeObservers()
    }

    func loadAudio(url: URL) {
        removeObservers()
        configureAudioSession()
        loadGeneration &+= 1
        let gen = loadGeneration

        let asset = AVURLAsset(url: url)
        let item = AVPlayerItem(asset: asset)
        // Preserve pitch when rate != 1.0 (varispeed w/o chipmunk effect).
        item.audioTimePitchAlgorithm = .timeDomain
        playerItem = item

        let p = AVPlayer(playerItem: item)
        p.automaticallyWaitsToMinimizeStalling = true
        player = p

        // Periodic time observer drives subtitle sync (~15 Hz — plenty for word highlight).
        let interval = CMTime(seconds: 1.0 / 15.0, preferredTimescale: 600)
        timeObserver = p.addPeriodicTimeObserver(forInterval: interval, queue: .main) { [weak self] t in
            guard let self else { return }
            let s = CMTimeGetSeconds(t)
            if s.isFinite { self.onTimeUpdate?(s) }
        }

        endObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemDidPlayToEndTime,
            object: item,
            queue: .main
        ) { [weak self] _ in
            self?.onPlaybackFinished?()
        }

        // Mid-stream failure (connection drop, corrupted payload tail, timeout).
        failObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemFailedToPlayToEndTime,
            object: item,
            queue: .main
        ) { [weak self] note in
            guard let self else { return }
            let err = note.userInfo?[AVPlayerItemFailedToPlayToEndTimeErrorKey] as? Error
            self.onLoadFailed?(err?.localizedDescription ?? "播放中斷")
        }

        // Network stall (buffer starved) — surfaces to UI as "緩衝中…" hint if desired.
        stallObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemPlaybackStalled,
            object: item,
            queue: .main
        ) { [weak self] _ in
            // Non-fatal: AVPlayer recovers automatically. Could expose via callback later.
            _ = self
        }

        // KVO on item.status — catches failures that surface AFTER isPlayable probe
        // returned true (404 with range, corrupted headers discovered during decode).
        statusObserver = item.observe(\.status, options: [.new]) { [weak self] observed, _ in
            guard let self else { return }
            if observed.status == .failed {
                let msg = observed.error?.localizedDescription ?? "音訊項目失敗"
                DispatchQueue.main.async { self.onLoadFailed?(msg) }
            }
        }

        // Duration + readiness — loaded async from remote asset metadata.
        // Capture `gen`; bail if a newer load has started by the time we resume.
        Task { @MainActor [weak self] in
            guard let self, gen == self.loadGeneration else { return }
            do {
                let d = try await asset.load(.duration)
                guard gen == self.loadGeneration else { return }
                let s = CMTimeGetSeconds(d)
                if s.isFinite, s > 0 {
                    self.duration = s
                    self.onDurationLoaded?(s)
                }
            } catch {
                // Keep duration at 0 — player still streams, just scrubber UX degrades.
            }
            // Only signal ready when the asset is genuinely playable; otherwise surface
            // the failure so the UI can show an error state instead of hanging in .loading.
            let playable: Bool
            do {
                playable = try await asset.load(.isPlayable)
            } catch {
                guard gen == self.loadGeneration else { return }
                self.onLoadFailed?(error.localizedDescription)
                return
            }
            guard gen == self.loadGeneration else { return }
            if playable {
                self.onReadyToPlay?()
            } else {
                self.onLoadFailed?("音訊無法播放")
            }
        }
    }

    func play() {
        guard let p = player else { return }
        p.play()
        p.rate = playbackRate  // AVPlayer resets rate to 1.0 on play; re-apply.
    }

    func pause() {
        player?.pause()
    }

    func seek(to time: TimeInterval, autoResume: Bool) {
        guard let p = player else { return }
        let clamped = max(0, duration > 0 ? min(time, duration) : time)
        let cm = CMTime(seconds: clamped, preferredTimescale: 600)
        p.seek(to: cm, toleranceBefore: .zero, toleranceAfter: .zero) { [weak self] _ in
            guard let self else { return }
            self.onTimeUpdate?(clamped)
            if autoResume {
                p.play()
                p.rate = self.playbackRate
            }
        }
    }

    func setRate(_ rate: Float) {
        playbackRate = max(0.5, min(rate, 2.0))
        // Only apply to an actively-playing player; otherwise AVPlayer treats non-zero
        // rate as a play command even when we intended to stay paused.
        if player?.timeControlStatus == .playing {
            player?.rate = playbackRate
        }
    }

    var currentTime: TimeInterval {
        guard let p = player else { return 0 }
        let t = CMTimeGetSeconds(p.currentTime())
        return t.isFinite ? t : 0
    }

    var isPlaying: Bool {
        player?.timeControlStatus == .playing
    }

    // MARK: - Private

    private func configureAudioSession() {
        #if os(iOS)
        let session = AVAudioSession.sharedInstance()
        try? session.setCategory(.playback, mode: .spokenAudio)
        try? session.setActive(true)
        #endif
    }

    /// Full teardown — frees the AVPlayerItem so buffering stops and the asset
    /// reader releases its network handle. Call from view `.onDisappear`.
    func stop() {
        removeObservers()
    }

    private func removeObservers() {
        if let p = player, let obs = timeObserver {
            p.removeTimeObserver(obs)
        }
        timeObserver = nil
        if let obs = endObserver {
            NotificationCenter.default.removeObserver(obs)
        }
        endObserver = nil
        if let obs = failObserver {
            NotificationCenter.default.removeObserver(obs)
        }
        failObserver = nil
        if let obs = stallObserver {
            NotificationCenter.default.removeObserver(obs)
        }
        stallObserver = nil
        statusObserver?.invalidate()
        statusObserver = nil
        player?.pause()
        // Detach the item so AVPlayer releases the underlying asset reader
        // (pause alone keeps network buffering alive).
        player?.replaceCurrentItem(with: nil)
        player = nil
        playerItem = nil
        duration = 0
    }
}

enum PodcastAudioEngineError: LocalizedError {
    case invalidFile
    var errorDescription: String? { "Invalid audio file" }
}
