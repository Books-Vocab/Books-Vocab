import Testing
@testable import BooksAndVocab

@Suite("SettingsPresenterState")
struct SettingsPresenterStateTests {
    @Test func syncLifecycleTransitionsFromErrorThroughRetryToSuccess() {
        var lifecycle = SettingsSyncLifecycle.idle

        #expect(lifecycle == .idle)
        #expect(lifecycle.begin())
        #expect(lifecycle == .syncing)

        #expect(lifecycle.fail(message: L10n.string("同步失敗")))
        #expect(lifecycle == .terminalError(message: L10n.string("同步失敗")))

        #expect(lifecycle.retry())
        #expect(lifecycle == .retry)
        #expect(lifecycle.succeed())
        #expect(lifecycle == .terminalSuccess)

        #expect(lifecycle.dismiss())
        #expect(lifecycle == .dismissed)
        #expect(lifecycle.reset())
        #expect(lifecycle == .idle)
    }

    @Test func failedBoolTransitionIsObservableAndLeavesStateUnchanged() {
        var lifecycle = SettingsSyncLifecycle.idle

        #expect(!lifecycle.succeed())
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
