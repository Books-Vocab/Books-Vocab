#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the podcast series "follow" toggle.
///
/// `PodcastFollowToggle` itself is a pure helper; the user-facing surface is the
/// star glyph button (`AppToolbarGlyph` with `star` / `star.fill`) wired to
/// `PodcastFollowToggle.perform`. These scenarios render that button against a
/// real `PodcastSeries` and exercise the three meaningful states:
///   - unfollowed (hollow star)
///   - followed (filled star)
///   - rolled-back (a save that reports failure reverts the optimistic flip, so
///     the star snaps back to its prior state instead of lying)
enum PodcastFollowToggleScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Podcast Follow Toggle") {
            Scenario("Unfollowed", layout: .fill) {
                FollowToggleScene(initiallyFollowed: false, saveSucceeds: true)
            }
            Scenario("Followed", layout: .fill) {
                FollowToggleScene(initiallyFollowed: true, saveSucceeds: true)
            }
            Scenario("Save fails → rolls back", layout: .fill) {
                FollowToggleScene(initiallyFollowed: false, saveSucceeds: false)
            }
        }
    }
}

// MARK: - Scene harness

/// Reconstructs `PodcastEpisodeListView.followToggleButton` in isolation so the
/// optimistic-flip-with-rollback contract is visible in a static snapshot.
private struct FollowToggleScene: View {
    let saveSucceeds: Bool

    @State private var series: PodcastSeries
    @State private var lastOutcome: PodcastFollowToggle.Outcome?

    init(initiallyFollowed: Bool, saveSucceeds: Bool) {
        self.saveSucceeds = saveSucceeds
        let seeded = PodcastSeries(
            remoteId: "series-001",
            title: "深夜英語電台",
            hostNames: ["Ava", "Noah"]
        )
        seeded.isFollowed = initiallyFollowed
        self._series = State(initialValue: seeded)
    }

    private var isFollowed: Bool { series.isFollowed }

    var body: some View {
        AppThemeContainer {
            VStack(spacing: 24) {
                Text(series.title)
                    .font(.headline)

                Button(action: toggleFollow) {
                    AppToolbarGlyph(systemImage: isFollowed ? "star.fill" : "star")
                }
                .accessibilityIdentifier("podcast.followToggle")

                VStack(spacing: 4) {
                    Text(isFollowed ? "已追蹤" : "未追蹤")
                        .font(.subheadline)
                    if let lastOutcome {
                        Text(outcomeLabel(lastOutcome))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    } else {
                        Text(saveSucceeds ? "點擊可追蹤（儲存成功）" : "點擊將觸發儲存失敗 → 回滾")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .padding()
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    private func toggleFollow() {
        let outcome = PodcastFollowToggle.perform(series: series) { saveSucceeds }
        lastOutcome = outcome
    }

    private func outcomeLabel(_ outcome: PodcastFollowToggle.Outcome) -> String {
        switch outcome {
        case .saved: return "上次結果：已儲存"
        case .rolledBack: return "上次結果：儲存失敗，已回滾"
        }
    }
}
#endif
