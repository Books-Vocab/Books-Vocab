import SwiftUI

@MainActor
final class TodayReviewAutoplayController {
    private let settingsStore: ReviewSettingsStore
    private var task: Task<Void, Never>?

    private(set) var isPlaying = false
    private(set) var isPaused = false
    private(set) var speed: AutoplaySpeed
    private(set) var soundEnabled: Bool

    init(settingsStore: ReviewSettingsStore = .shared) {
        self.settingsStore = settingsStore
        self.speed = settingsStore.settings.autoplaySpeed
        self.soundEnabled = settingsStore.settings.autoplaySoundEnabled
    }

    var isLoopActive: Bool { isPlaying && !isPaused }

    func togglePlayback(
        restartLoop: @escaping @MainActor () -> Void
    ) {
        if isPlaying {
            stop()
        } else {
            isPlaying = true
            isPaused = false
            restartLoop()
        }
    }

    func togglePause(
        restartLoop: @escaping @MainActor () -> Void
    ) {
        isPaused.toggle()
        if !isPaused {
            restartLoop()
        }
    }

    func stop() {
        task?.cancel()
        task = nil
        isPlaying = false
        isPaused = false
    }

    func changeSpeed(
        to speed: AutoplaySpeed,
        restartLoop: @escaping @MainActor () -> Void
    ) {
        self.speed = speed
        persist { $0.autoplaySpeed = speed }
        if isLoopActive {
            restartLoop()
        }
    }

    func toggleSound() {
        soundEnabled.toggle()
        let enabled = soundEnabled
        persist { $0.autoplaySoundEnabled = enabled }
    }

    func cancelLoopTask() {
        task?.cancel()
        task = nil
    }

    func startOrRestartLoop(
        isComplete: @escaping @MainActor () -> Bool,
        shouldReveal: @escaping @MainActor () -> Bool,
        reveal: @escaping @MainActor () -> Void,
        advance: @escaping @MainActor () -> Bool
    ) {
        cancelLoopTask()
        task = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                guard let self, self.isLoopActive else { return }
                guard !isComplete() else {
                    self.stop()
                    return
                }

                if shouldReveal() {
                    try? await Task.sleep(for: self.speed.revealDelay)
                    guard !Task.isCancelled, self.isLoopActive else { return }
                    reveal()
                }

                try? await Task.sleep(for: self.speed.stayDelay)
                guard !Task.isCancelled, self.isLoopActive else { return }

                if !advance() {
                    self.stop()
                    return
                }
            }
        }
    }

    private func persist(_ mutate: (inout ReviewSettings) -> Void) {
        var settings = settingsStore.settings
        mutate(&settings)
        settingsStore.update(settings)
    }
}
