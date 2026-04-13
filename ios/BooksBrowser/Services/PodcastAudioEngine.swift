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

    private(set) var playbackRate: Float = 1.0
    private(set) var duration: TimeInterval = 0

    var onTimeUpdate: ((TimeInterval) -> Void)?
    var onPlaybackFinished: (() -> Void)?
    var onDurationLoaded: ((TimeInterval) -> Void)?
    var onReadyToPlay: (() -> Void)?

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

    func loadAudio(url: URL) throws {
        removeObservers()
        configureAudioSession()

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

        // Duration + readiness — loaded async from remote asset metadata.
        Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                let d = try await asset.load(.duration)
                let s = CMTimeGetSeconds(d)
                if s.isFinite, s > 0 {
                    self.duration = s
                    self.onDurationLoaded?(s)
                }
            } catch {
                // Keep duration at 0 — player still streams, just scrubber UX degrades.
            }
            // Signal ready once the item is playable (first playable byte buffered).
            _ = try? await asset.load(.isPlayable)
            self.onReadyToPlay?()
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

    private func removeObservers() {
        if let p = player, let obs = timeObserver {
            p.removeTimeObserver(obs)
        }
        timeObserver = nil
        if let obs = endObserver {
            NotificationCenter.default.removeObserver(obs)
        }
        endObserver = nil
        player?.pause()
        player = nil
        playerItem = nil
        duration = 0
    }
}

enum PodcastAudioEngineError: LocalizedError {
    case invalidFile
    var errorDescription: String? { "Invalid audio file" }
}
