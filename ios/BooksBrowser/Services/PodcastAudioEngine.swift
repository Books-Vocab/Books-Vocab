import Foundation
import AVFoundation
#if os(iOS)
import MediaPlayer
#endif

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
    private var stallWatchdog: Task<Void, Never>?
    private var remoteCommandTargets: [(MPRemoteCommand, Any)] = []
    private var nowPlayingTitle: String = ""
    private var nowPlayingArtist: String = ""
    private var timeControlObserver: NSKeyValueObservation?
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
    /// System forced playback to pause (interruption began, headphones unplugged).
    var onSystemPause: (() -> Void)?
    /// System hinted we should resume after interruption ended.
    var onSystemResume: (() -> Void)?

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

        // preferPreciseDuration: CBR/VBR MP3 duration from HTTP headers is a
        // rough estimate; precise parsing prevents end-of-episode scrubber
        // misalignment and subtitle drift.
        let asset = AVURLAsset(
            url: url,
            options: [AVURLAssetPreferPreciseDurationAndTimingKey: true]
        )
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
            #if os(iOS)
            self?.updateNowPlayingInfo(rateOverride: 0)
            #endif
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

        // KVO on player.timeControlStatus — arms the stall watchdog precisely
        // when buffering begins, and cancels it the moment playback resumes.
        // Covers post-seek stalls without false positives after successful play.
        // Also refreshes lock-screen info so the play/pause icon matches reality
        // (play() fires before timeControlStatus flips, which would otherwise
        // freeze NowPlayingInfo.playbackRate at 0).
        timeControlObserver = p.observe(\.timeControlStatus, options: [.new]) { [weak self] observed, _ in
            guard let self else { return }
            DispatchQueue.main.async {
                guard gen == self.loadGeneration else { return }
                switch observed.timeControlStatus {
                case .waitingToPlayAtSpecifiedRate:
                    self.startStallWatchdog()
                case .playing, .paused:
                    self.stallWatchdog?.cancel()
                    self.stallWatchdog = nil
                @unknown default:
                    break
                }
                #if os(iOS)
                self.updateNowPlayingInfo()
                #endif
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
                    #if os(iOS)
                    self.updateNowPlayingInfo()
                    #endif
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
        // Replay-after-end: AVPlayer.play() is a no-op once currentTime has
        // reached duration (actionAtItemEnd defaults to .pause). Seek to 0
        // first so tapping play on a finished episode actually replays it.
        if duration > 0, currentTime >= duration - 0.1 {
            p.seek(to: .zero, toleranceBefore: .zero, toleranceAfter: .zero)
        }
        p.play()
        p.rate = playbackRate  // AVPlayer resets rate to 1.0 on play; re-apply.
        #if os(iOS)
        // Force intended rate — timeControlStatus lags reality on first play.
        updateNowPlayingInfo(rateOverride: Double(playbackRate))
        #endif
    }

    func pause() {
        player?.pause()
        stallWatchdog?.cancel()
        stallWatchdog = nil
        #if os(iOS)
        updateNowPlayingInfo(rateOverride: 0)
        #endif
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
            #if os(iOS)
            self.updateNowPlayingInfo()
            #endif
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
                self?.stallWatchdog?.cancel()
                self?.stallWatchdog = nil
                self?.onSystemPause?()
            case .ended:
                try? AVAudioSession.sharedInstance().setActive(true)
                let opts = (info[AVAudioSessionInterruptionOptionKey] as? UInt).map {
                    AVAudioSession.InterruptionOptions(rawValue: $0)
                } ?? []
                if opts.contains(.shouldResume) {
                    self?.player?.play()
                    self?.player?.rate = self?.playbackRate ?? 1.0
                    self?.onSystemResume?()
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
                self?.stallWatchdog?.cancel()
                self?.stallWatchdog = nil
                self?.onSystemPause?()
            }
        }
    }
    #endif

    /// Full teardown — frees the AVPlayerItem so buffering stops and the asset
    /// reader releases its network handle. Call from view `.onDisappear`.
    /// Bumps loadGeneration so any in-flight async load task bails on its next
    /// generation check instead of firing callbacks on a torn-down VM.
    /// Release the current player + item + observers. Use when another load is
    /// about to take over (retry / episode swap) — leaves audio session active
    /// and remote commands registered so there's no ducking pulse or lock-screen
    /// flicker during the handoff.
    func stop() {
        loadGeneration &+= 1
        stallWatchdog?.cancel()
        stallWatchdog = nil
        removeObservers()
        #if os(iOS)
        // Unregister remote commands so a new engine can re-register cleanly.
        // MPRemoteCommandCenter is a process-wide singleton; without this, every
        // retry / episode swap would add a fresh target on top of the old one,
        // producing a growing chain of handlers on dead engines. The new engine's
        // configureNowPlaying() re-registers immediately so the lock-screen
        // remains responsive throughout the handoff.
        unregisterRemoteCommands()
        #endif
    }

    /// True terminal teardown — use when the user is leaving the player entirely.
    /// Also deactivates the audio session + clears lock-screen info + removes
    /// remote-command targets so other apps (Spotify, etc.) regain audio focus.
    func shutdown() {
        stop()
        #if os(iOS)
        unregisterRemoteCommands()
        MPNowPlayingInfoCenter.default().nowPlayingInfo = nil
        try? AVAudioSession.sharedInstance().setActive(
            false,
            options: [.notifyOthersOnDeactivation]
        )
        #endif
    }

    /// Populate lock-screen / Control Center metadata + wire remote commands
    /// (play / pause / skip ±15s / scrubbing). Call from VM after loadEpisode
    /// with the episode title + host names.
    func configureNowPlaying(title: String, artist: String) {
        #if os(iOS)
        nowPlayingTitle = title
        nowPlayingArtist = artist
        registerRemoteCommands()
        updateNowPlayingInfo()
        #endif
    }

    #if os(iOS)
    private func registerRemoteCommands() {
        guard remoteCommandTargets.isEmpty else { return }
        let center = MPRemoteCommandCenter.shared()
        // Disable commands we don't support so lock-screen doesn't show dead
        // buttons (prev/next, seek, shuffle, repeat).
        center.nextTrackCommand.isEnabled = false
        center.previousTrackCommand.isEnabled = false
        center.seekForwardCommand.isEnabled = false
        center.seekBackwardCommand.isEnabled = false
        center.changeRepeatModeCommand.isEnabled = false
        center.changeShuffleModeCommand.isEnabled = false
        // changePlaybackPositionCommand is disabled by default — enable it
        // explicitly so the lock-screen scrubber is draggable.
        center.changePlaybackPositionCommand.isEnabled = true
        let play = center.playCommand.addTarget { [weak self] _ in
            self?.play(); return .success
        }
        remoteCommandTargets.append((center.playCommand, play))
        let pause = center.pauseCommand.addTarget { [weak self] _ in
            self?.pause(); return .success
        }
        remoteCommandTargets.append((center.pauseCommand, pause))
        center.skipForwardCommand.preferredIntervals = [15]
        let fwd = center.skipForwardCommand.addTarget { [weak self] _ in
            guard let self else { return .commandFailed }
            // Use timeControlStatus != .paused as "intended to play" proxy —
            // passes through stalls (.waitingToPlayAtSpecifiedRate) correctly.
            let shouldResume = self.player?.timeControlStatus != .paused
            self.seek(to: self.currentTime + 15, autoResume: shouldResume)
            return .success
        }
        remoteCommandTargets.append((center.skipForwardCommand, fwd))
        center.skipBackwardCommand.preferredIntervals = [15]
        let back = center.skipBackwardCommand.addTarget { [weak self] _ in
            guard let self else { return .commandFailed }
            let shouldResume = self.player?.timeControlStatus != .paused
            self.seek(to: max(0, self.currentTime - 15), autoResume: shouldResume)
            return .success
        }
        remoteCommandTargets.append((center.skipBackwardCommand, back))
        let scrub = center.changePlaybackPositionCommand.addTarget { [weak self] event in
            guard let self,
                  let pos = (event as? MPChangePlaybackPositionCommandEvent)?.positionTime
            else { return .commandFailed }
            let shouldResume = self.player?.timeControlStatus != .paused
            self.seek(to: pos, autoResume: shouldResume)
            return .success
        }
        remoteCommandTargets.append((center.changePlaybackPositionCommand, scrub))
    }

    private func unregisterRemoteCommands() {
        for (command, token) in remoteCommandTargets {
            command.removeTarget(token)
        }
        remoteCommandTargets.removeAll()
    }

    /// Explicit override for the published playback rate. `play()` / `pause()`
    /// pass what the user *intends* so the lock-screen icon flips immediately,
    /// rather than sampling `timeControlStatus` which typically lags by one RTT
    /// while AVPlayer buffers the first segment.
    private func updateNowPlayingInfo(rateOverride: Double? = nil) {
        var info: [String: Any] = [:]
        info[MPMediaItemPropertyTitle] = nowPlayingTitle
        info[MPMediaItemPropertyArtist] = nowPlayingArtist
        if duration > 0 {
            info[MPMediaItemPropertyPlaybackDuration] = duration
        }
        info[MPNowPlayingInfoPropertyElapsedPlaybackTime] = currentTime
        let rate = rateOverride ?? (isPlaying ? Double(playbackRate) : 0)
        info[MPNowPlayingInfoPropertyPlaybackRate] = rate
        MPNowPlayingInfoCenter.default().nowPlayingInfo = info
    }
    #endif

    /// Watchdog: if AVPlayer stays in `.waitingToPlayAtSpecifiedRate` for >15s
    /// (network stall the AVFoundation error path won't catch), surface a
    /// user-visible error instead of leaving the UI frozen.
    private func startStallWatchdog() {
        stallWatchdog?.cancel()
        stallWatchdog = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(15))
            guard let self, !Task.isCancelled else { return }
            if self.player?.timeControlStatus == .waitingToPlayAtSpecifiedRate {
                self.onLoadFailed?("網路緩衝逾時")
            }
        }
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
        timeControlObserver?.invalidate()
        timeControlObserver = nil
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
        // Session deactivation moved to stop() to avoid the
        // deactivate→reactivate pulse on every loadAudio retry.
    }
}

enum PodcastAudioEngineError: LocalizedError {
    case invalidFile
    var errorDescription: String? { "Invalid audio file" }
}
