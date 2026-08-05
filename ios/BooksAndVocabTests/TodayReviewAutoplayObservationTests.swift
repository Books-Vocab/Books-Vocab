//
//  TodayReviewAutoplayObservationTests.swift
//  Books & Vocab Tests
//
//  Regression guard for the autoplay chrome freeze (使用者回報:播放模式進入有延遲、
//  按第二下出不去、退出後再也進不去)。
//
//  根因:`TodayReviewAutoplayController` 曾是 plain class,卻被 `@Observable`
//  `TodayReviewState` 以 computed property 把 4 個 playback 狀態投影給 view 讀
//  (`TodayReviewState.swift` 的 isAutoPlaying / isAutoPlayPaused / autoplaySpeed /
//  autoplaySoundEnabled)。被持有的型別沒有 registrar → 讀它登記不到依賴 →
//  切 autoplay 不會 invalidate `TodayReviewView.body`。
//
//  失效是**非對稱**的:開啟方向會被 loop 自己的 `session` mutation 延遲自癒
//  (所以症狀是「延遲」而非「永遠不動」),關閉方向永遠不癒 (`stop()` 只碰 controller,
//  且 loop 已死、之後再無變更可觸發重繪) → 播放列永久卡住。**所以 ON / OFF 兩個方向
//  都必須斷言**;只測 ON 會綠了而「出不去」仍在。
//
//  注意這裡的 `withObservationTracking` 用法**不同於** `TodayReviewCacheWindowTests`
//  檔頭記載的 false-green 陷阱:那條講的是「假通知」——mutation 發生在 apply closure
//  *執行中*(inline `_modify`),onChange 尚未武裝,所以有 bug 也綠。本檔測的是
//  「**缺**通知」——mutation 在 apply closure *回傳後*,onChange 已武裝。
//  缺通知可證偽,假通知不可。
//
//  另一個必須避開的假綠:apply closure **只能讀單一投影**。若為了「忠實模擬 body」
//  寫成 `_ = state.presenterState`,追蹤集合會被 session / cardCache / scoring 填滿,
//  autoplay loop 在 1-8 秒後 mutate `session` 就讓任何 await 版本的斷言恆綠。
//

import Foundation
import Observation
import Testing
@testable import BooksAndVocab

/// `withObservationTracking` 的 onChange 是 `@Sendable` 非隔離閉包,而受測型別是
/// `@MainActor`。用 reference box 承接旗標,避免捕獲 actor-isolated 的區域變數。
private final class NotificationFlag: @unchecked Sendable {
    var fired = false
}

@MainActor
struct TodayReviewAutoplayObservationTests {

    // MARK: - Fixtures

    /// Hermetic settings store(比照 `ReviewSettingsStoreAutoplayTests`):sound / speed
    /// 的斷言會寫入持久層,不可污染 `.standard`。
    private func makeSettingsStore() -> ReviewSettingsStore {
        let suite = "test.autoplay.observation.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defaults.removePersistentDomain(forName: suite)
        return ReviewSettingsStore(defaults: defaults, cloud: FakeCloudKVStore())
    }

    private func makeController() -> TodayReviewAutoplayController {
        TodayReviewAutoplayController(settingsStore: makeSettingsStore())
    }

    private func makeState() -> TodayReviewState {
        let entries = (0..<3).map { index -> VocabularyEntry in
            let entry = VocabularyEntry(
                word: "word-\(index)",
                translation: "translation-\(index)",
                context: "A sample sentence for word \(index).",
                bookTitle: "Sample"
            )
            entry.markSynced()
            return entry
        }
        return TodayReviewState(entries: entries, allEntries: entries, currentUserID: nil)
    }

    /// 讀 → 動作 → 回報「觀察者有沒有被通知」。`read` 刻意只讀一個投影(見檔頭)。
    private func didNotify(reading read: () -> Void, whenPerforming action: () -> Void) -> Bool {
        let flag = NotificationFlag()
        withObservationTracking {
            read()
        } onChange: {
            flag.fired = true
        }
        action()
        return flag.fired
    }

    // MARK: - Controller 層(純單元:可注入 store、restartLoop 為 no-op 故不起 Task)

    @Test func startingPlaybackNotifiesObservers() {
        let controller = makeController()
        let fired = didNotify(
            reading: { _ = controller.isPlaying },
            whenPerforming: { controller.togglePlayback(restartLoop: {}) }
        )
        #expect(fired, "開啟 autoplay 未通知觀察者 → chrome 不會切成播放列(症狀:進入有延遲)")
    }

    @Test func stoppingPlaybackNotifiesObservers() {
        // 使用者回報的頭號症狀:按第二下沒反應、播放列卡住不消失。
        // 這個方向沒有任何 loop mutation 可以事後自癒,漏通知 = 永久凍結。
        let controller = makeController()
        controller.togglePlayback(restartLoop: {})
        let fired = didNotify(
            reading: { _ = controller.isPlaying },
            whenPerforming: { controller.togglePlayback(restartLoop: {}) }
        )
        #expect(fired, "關閉 autoplay 未通知觀察者 → 播放列永久卡在畫面上(症狀:出不去)")
    }

    @Test func pauseToggleNotifiesObservers() {
        let controller = makeController()
        controller.togglePlayback(restartLoop: {})
        let fired = didNotify(
            reading: { _ = controller.isPaused },
            whenPerforming: { controller.togglePause(restartLoop: {}) }
        )
        #expect(fired, "暫停鍵未通知觀察者 → play/pause 圖示不會切換")
    }

    @Test func soundToggleNotifiesObservers() {
        let controller = makeController()
        let fired = didNotify(
            reading: { _ = controller.soundEnabled },
            whenPerforming: { controller.toggleSound() }
        )
        #expect(fired, "喇叭鍵未通知觀察者 → 圖示不會切換")
    }

    @Test func speedChangeNotifiesObservers() {
        let controller = makeController()
        let next = controller.speed.next
        let fired = didNotify(
            reading: { _ = controller.speed },
            whenPerforming: { controller.changeSpeed(to: next, restartLoop: {}) }
        )
        #expect(fired, "速度鍵未通知觀察者 → 速度藥丸文字不會更新")
    }

    // MARK: - 同值不寫守衛(teardown 幀不該重評整棵 body)

    @Test func stoppingAnIdleControllerDoesNotNotify() {
        // `TodayReviewView.onDisappear` 對「從未用過 autoplay」的 session 也會呼叫
        // stopAutoPlay();在 Observation 世界裡,冪等必須包含「不發通知」。
        let controller = makeController()
        let fired = didNotify(
            reading: { _ = controller.isPlaying },
            whenPerforming: { controller.stop() }
        )
        #expect(!fired, "對 idle controller 呼叫 stop() 發出了假通知 → dismiss 動畫幀白做一次全樹重評")
    }

    @Test func pauseIsIgnoredWhenNotPlaying() {
        // 守衛下沉到真值旁邊:原本唯一的 guard 在 performReviewIntent,
        // 任何新 caller 都會踩到「沒在播卻能進入 paused」。
        let controller = makeController()
        controller.togglePause(restartLoop: {})
        #expect(!controller.isPaused, "沒在播放時仍被切進 paused 狀態")
    }

    // MARK: - State 投影契約(綁使用者看得到的契約,不綁實作形狀)

    @Test func statePlaybackProjectionNotifiesOnStart() {
        let state = makeState()
        let fired = didNotify(
            reading: { _ = state.isAutoPlaying },
            whenPerforming: { state.toggleAutoPlay() }
        )
        state.stopAutoPlay()
        #expect(fired, "TodayReviewState.isAutoPlaying 的投影未傳遞通知 → TodayReviewView.body 不會重評")
    }

    @Test func statePlaybackProjectionNotifiesOnStop() {
        let state = makeState()
        state.toggleAutoPlay()
        let fired = didNotify(
            reading: { _ = state.isAutoPlaying },
            whenPerforming: { state.toggleAutoPlay() }
        )
        state.stopAutoPlay()
        #expect(fired, "TodayReviewState.isAutoPlaying 關閉方向的投影未傳遞通知")
    }

    @Test func statePauseProjectionNotifiesObservers() {
        let state = makeState()
        state.toggleAutoPlay()
        let fired = didNotify(
            reading: { _ = state.isAutoPlayPaused },
            whenPerforming: { state.toggleAutoPlayPause() }
        )
        state.stopAutoPlay()
        #expect(fired, "TodayReviewState.isAutoPlayPaused 的投影未傳遞通知")
    }

    // `TodayReviewState` 的 controller 綁 `ReviewSettingsStore.shared`(無注入點),
    // 所以這兩條會寫到 `.standard`。改完立刻還原,讓整輪測試維持 hermetic
    // (autoplay 兩個 key 只走 local 寫入,不推進 mode/pause 的 LWW clock)。
    @Test func stateSoundProjectionNotifiesObservers() {
        let state = makeState()
        let original = state.autoplaySoundEnabled
        let fired = didNotify(
            reading: { _ = state.autoplaySoundEnabled },
            whenPerforming: { state.toggleAutoplaySound() }
        )
        if state.autoplaySoundEnabled != original { state.toggleAutoplaySound() }
        #expect(fired, "TodayReviewState.autoplaySoundEnabled 的投影未傳遞通知")
    }

    @Test func stateSpeedProjectionNotifiesObservers() {
        let state = makeState()
        let original = state.autoplaySpeed
        let fired = didNotify(
            reading: { _ = state.autoplaySpeed },
            whenPerforming: { state.changeAutoplaySpeed(to: original.next) }
        )
        state.changeAutoplaySpeed(to: original)
        #expect(fired, "TodayReviewState.autoplaySpeed 的投影未傳遞通知")
    }
}
