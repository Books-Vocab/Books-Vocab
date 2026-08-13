import Testing
@testable import BooksAndVocab

@Suite("SettingsPresenterState")
struct SettingsPresenterStateTests {
    @Test func syncLifecycleTransitionsFromErrorThroughRetryToSuccess() {
        var lifecycle = SettingsSyncLifecycle.idle

        #expect(lifecycle == .idle)
        let didBegin = lifecycle.begin()
        #expect(didBegin)
        #expect(lifecycle == .syncing)

        let didFail = lifecycle.fail(message: L10n.string("同步失敗"))
        #expect(didFail)
        #expect(lifecycle == .terminalError(message: L10n.string("同步失敗")))

        let didRetry = lifecycle.retry()
        #expect(didRetry)
        #expect(lifecycle == .retry)
        let didSucceed = lifecycle.succeed()
        #expect(didSucceed)
        #expect(lifecycle == .terminalSuccess)

        let didDismiss = lifecycle.dismiss()
        #expect(didDismiss)
        #expect(lifecycle == .dismissed)
        let didReset = lifecycle.reset()
        #expect(didReset)
        #expect(lifecycle == .idle)
    }

    @Test func failedBoolTransitionIsObservableAndLeavesStateUnchanged() {
        var lifecycle = SettingsSyncLifecycle.idle

        let didSucceed = lifecycle.succeed()
        #expect(!didSucceed)
        #expect(lifecycle == .idle)
    }

    @Test func selectedReviewModeUsesModeDisplayNameWhenActive() {
        var settings = ReviewSettings.default
        settings.mode = .relaxed
        settings.resumeProgress()

        #expect(
            SettingsPresenterState.PreferencesSection.reviewModeDisplayName(for: settings)
                == settings.mode.displayName
        )
    }

    @Test func selectedReviewModeShowsFrozenPrefixWhenPaused() {
        var settings = ReviewSettings.default
        settings.mode = .intensive
        settings.pauseProgress()

        #expect(
            SettingsPresenterState.PreferencesSection.reviewModeDisplayName(for: settings)
                == L10n.format("已凍結 · %@", settings.mode.displayName)
        )
    }

    @Test func selectedReviewModeKeepsFrozenPrefixAfterModeChanges() {
        var settings = ReviewSettings.default
        settings.pauseProgress()
        settings.mode = .custom

        #expect(
            SettingsPresenterState.PreferencesSection.reviewModeDisplayName(for: settings)
                == L10n.format("已凍結 · %@", ReviewSettingsMode.custom.displayName)
        )
    }
}
