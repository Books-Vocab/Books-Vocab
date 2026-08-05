import SwiftUI

/// Autoplay playback state / settings persistence / loop task。
///
/// **必須維持 `@Observable`**:下面四個 playback 狀態是被 `TodayReviewState` 的
/// computed property 投影給 `TodayReviewView.body` 讀的(`isAutoPlaying` /
/// `isAutoPlayPaused` / `autoplaySpeed` / `autoplaySoundEnabled`)。被持有的型別若沒有
/// registrar,讀它就登記不到依賴,切 autoplay 不會 invalidate view——而且失效是
/// **非對稱**的:開啟方向會被 loop 自己的 `session` mutation 延遲自癒(看起來只是
/// 「有點延遲」),關閉方向永遠不癒 → 播放列永久卡在畫面上、按什麼都沒反應。
/// 把持有它的 `let` 改成 `var` **不能**代替本標註(寫的是被指物件內部,
/// `withMutation(\.autoplay)` 永不觸發)。契約由 `TodayReviewAutoplayObservationTests` 釘住。
@Observable @MainActor
final class TodayReviewAutoplayController {
    @ObservationIgnored private let settingsStore: ReviewSettingsStore
    /// 純內部排程 handle,**必須**豁免:播放中每張卡都會 `startOrRestartLoop`
    /// (cancel + 重新賦值),被觀察的話就是每卡兩次假通知,而一次假通知 =
    /// 整個 `TodayReviewView.body` 重算(重建 presenterState + 3 個 slot models)。
    @ObservationIgnored private var task: Task<Void, Never>?

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
        // 守衛下沉到真值旁邊:原本唯一的 guard 在 `performReviewIntent`,
        // 任何新 caller 都能把沒在播放的 controller 推進 paused。
        guard isPlaying else { return }
        isPaused.toggle()
        if !isPaused {
            restartLoop()
        }
    }

    /// Pause for a modal interruption (the layout editor). Never *starts* playback —
    /// a stopped autoplay stays stopped — and deliberately does not auto-resume:
    /// the user chose to change the card, so they resume when they are ready.
    func pauseForInterruption() {
        guard isPlaying, !isPaused else { return }
        isPaused = true
        cancelLoopTask()
    }

    func stop() {
        // 在 Observation 世界裡,冪等必須包含「不發通知」:`TodayReviewView.onDisappear`
        // 對從未用過 autoplay 的 session 也會呼叫這裡,而那正是 dismiss 動畫那幾格——
        // 不該為了寫兩個同值的 Bool 多做一次全樹 body 重評。
        guard isPlaying || isPaused || task != nil else { return }
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
