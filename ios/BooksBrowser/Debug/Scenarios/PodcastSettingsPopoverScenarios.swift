#if DEBUG && canImport(Playbook)
#if os(iOS)
import Playbook
import SwiftUI

/// Catalog scenarios for `PodcastSettingsPopover` — the in-player settings
/// sheet (subtitle size, highlight color, word-follow, auto-pause, sleep timer).
///
/// The popover takes `@Binding` params and an `@AppStorage` flag, plus reads
/// `\.readerSettings` from the environment (default `ReaderSettings.shared`),
/// so every scenario wraps it in a small `@MainActor` View struct that owns
/// the `@State` backing the bindings.
enum PodcastSettingsPopoverScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Podcast Settings Popover") {
            Scenario("Default", layout: .fill) {
                PodcastSettingsPopoverScene(
                    subtitleSize: .medium,
                    autoPauseOnLookup: true,
                    sleepTimerMode: .off,
                    sleepDeadline: nil
                )
            }

            Scenario("XXL · auto-pause off", layout: .fill) {
                PodcastSettingsPopoverScene(
                    subtitleSize: .xxLarge,
                    autoPauseOnLookup: false,
                    sleepTimerMode: .off,
                    sleepDeadline: nil
                )
            }

            Scenario("Sleep timer counting down", layout: .fill) {
                PodcastSettingsPopoverScene(
                    subtitleSize: .large,
                    autoPauseOnLookup: true,
                    sleepTimerMode: .minutes(15),
                    sleepDeadline: Date().addingTimeInterval(13 * 60 + 42)
                )
            }

            Scenario("End of episode timer", layout: .fill) {
                PodcastSettingsPopoverScene(
                    subtitleSize: .small,
                    autoPauseOnLookup: false,
                    sleepTimerMode: .endOfEpisode,
                    sleepDeadline: nil
                )
            }
        }
    }
}

// MARK: - Scene harness

/// `@MainActor`-isolated body owns the `@State` mirroring the popover's bindings.
private struct PodcastSettingsPopoverScene: View {
    @State private var subtitleSize: PodcastSubtitleSize
    @State private var autoPauseOnLookup: Bool
    @State private var sleepTimerMode: SleepTimerMode
    private let sleepDeadline: Date?

    init(
        subtitleSize: PodcastSubtitleSize,
        autoPauseOnLookup: Bool,
        sleepTimerMode: SleepTimerMode,
        sleepDeadline: Date?
    ) {
        self._subtitleSize = State(initialValue: subtitleSize)
        self._autoPauseOnLookup = State(initialValue: autoPauseOnLookup)
        self._sleepTimerMode = State(initialValue: sleepTimerMode)
        self.sleepDeadline = sleepDeadline
    }

    var body: some View {
        AppThemeContainer {
            PodcastSettingsPopover(
                subtitleSize: $subtitleSize,
                autoPauseOnLookup: $autoPauseOnLookup,
                sleepTimerMode: $sleepTimerMode,
                sleepDeadline: sleepDeadline
            )
            .padding()
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
#endif
