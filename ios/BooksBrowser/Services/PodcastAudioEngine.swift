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
    private var statusObserver: NSKeyValueObservation?
    private var interruptionObserver: NSObjectProtocol?
    private var routeChangeObserver: NSObjectProtocol?
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
        // `gen` capture: a later load must not inherit this old item's failure.
        failObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemFailedToPlayToEndTime,
            object: item,
            queue: .main
        ) { [weak self] note in
            guard let self, gen == self.loadGeneration else { return }
            let err = note.userInfo?[AVPlayerItemFailedToPlayToEndTimeErrorKey] as? Error
            self.onLoadFailed?(err?.localizedDescription ?? "播放中斷")
        }

        // KVO on item.status — catches failures that surface AFTER isPlayable probe
        // returned true (404 with range, corrupted headers discovered during decode).
        statusObserver = item.observe(\.status, options: [.new]) { [weak self] observed, _ in
            guard let self, observed.status == .failed else { return }
            let msg = observed.error?.localizedDescription ?? "音訊項目失敗"
            DispatchQueue.main.async {
                guard gen == self.loadGeneration else { return }
                self.onLoadFailed?(msg)
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
        registerAudioSessionObservers()
        #endif
    }

    #if os(iOS)
    private func registerAudioSessionObservers() {
        guard interruptionObserver == nil else { return }
        let nc = NotificationCenter.default
        interruptionObserver = nc.addObserver(
            forName: AVAudioSession.interruptionNotification,
            object: AVAudioSession.sharedInstance(),
            queue: .main
        ) { [weak self] note in
            guard
                let info = note.userInfo,
                let typeRaw = info[AVAudioSessionInterruptionTypeKey] as? UInt,
                let type = AVAudioSession.InterruptionType(rawValue: typeRaw)
            else { return }
            switch type {
            case .began:
                self?.player?.pause()
            case .ended:
                // Reactivate session + auto-resume only if system hints it.
                try? AVAudioSession.sharedInstance().setActive(true)
                let opts = (info[AVAudioSessionInterruptionOptionKey] as? UInt).map {
                    AVAudioSession.InterruptionOptions(rawValue: $0)
                } ?? []
                if opts.contains(.shouldResume) {
                    self?.player?.play()
                    self?.player?.rate = self?.playbackRate ?? 1.0
                }
            @unknown default:
                break
            }
        }
        routeChangeObserver = nc.addObserver(
            forName: AVAudioSession.routeChangeNotification,
            object: AVAudioSession.sharedInstance(),
            queue: .main
        ) { [weak self] note in
            guard
                let info = note.userInfo,
                let reasonRaw = info[AVAudioSessionRouteChangeReasonKey] as? UInt,
                let reason = AVAudioSession.RouteChangeReason(rawValue: reasonRaw)
            else { return }
            // Headphones unplugged / previous device unavailable → pause per HIG.
            if reason == .oldDeviceUnavailable {
                self?.player?.pause()
            }
        }
    }
    #endif

    /// Full teardown — frees the AVPlayerItem so buffering stops and the asset
    /// reader releases its network handle. Call from view `.onDisappear`.
    /// Bumps loadGeneration so any in-flight async load task bails on its next
    /// generation check instead of firing callbacks on a torn-down VM.
    func stop() {
        loadGeneration &+= 1
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
        statusObserver?.invalidate()
        statusObserver = nil
        if let obs = interruptionObserver {
            NotificationCenter.default.removeObserver(obs)
        }
        interruptionObserver = nil
        if let obs = routeChangeObserver {
            NotificationCenter.default.removeObserver(obs)
        }
        routeChangeObserver = nil
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
