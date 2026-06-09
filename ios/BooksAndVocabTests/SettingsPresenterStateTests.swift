import Testing
@testable import BooksAndVocab

@Suite("SettingsPresenterState")
struct SettingsPresenterStateTests {
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
