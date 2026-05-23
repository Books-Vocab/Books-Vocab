#if os(iOS)
import SwiftUI
import Inject

struct PodcastSubtitleView: View {
    @ObserveInjection private var inject
    let viewModel: PodcastPlayerViewModel
    let subtitleSize: PodcastSubtitleSize
    /// Re-runs only the subtitle fetch — wired to the inline failure retry.
    var onRetrySubtitle: () -> Void = {}

    @Environment(\.appSkin) private var skin

    var body: some View {
        ZStack {
            PodcastSentenceLevelView(
                sentences: viewModel.visibleSentences,
                renderState: viewModel.renderState,
                highlightedWordIndex: viewModel.highlightedWordIndex,
                hostNames: viewModel.hostNames,
                subtitleSize: subtitleSize,
                onSentenceTap: { viewModel.seek(to: $0.startTime) },
                onWordTap: viewModel.handleWordTap,
                onPhraseTap: viewModel.handlePhraseTap,
                onExplainTap: viewModel.handleExplainTap
            )

            // Subtitle fetch failed — surface an inline retry WITHOUT
            // interrupting audio playback (no toast, no full-screen error).
            if viewModel.subtitleState == .failed {
                subtitleFailureOverlay
                    .transition(.overlayFade)
            }
        }
        .animation(AppMotion.contentFade, value: viewModel.subtitleState)
        .enableInjection()
    }

    @ViewBuilder
    private var subtitleFailureOverlay: some View {
        AppStateMessageCard(
            title: "字幕載入失敗",
            systemImage: "captions.bubble",
            description: "音訊仍可正常播放",
            style: .vocab(skin)
        ) {
            Button {
                onRetrySubtitle()
            } label: {
                Label("重試", systemImage: "arrow.clockwise")
            }
            .buttonStyle(.appCompactAction(.primary))
            .accessibilityIdentifier("podcast.subtitleRetry")
        }
        .padding(.horizontal, skin.spacing.cardPadding)
    }
}
#endif
