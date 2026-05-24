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

            // Subtitle lifecycle overlays — keep audio uninterrupted. Loading
            // and unavailable used to share the empty bubble layer (state
            // matrix L407/L410); now each gets an explicit hint so the user
            // can tell "still fetching" from "this episode has no subtitle".
            switch viewModel.subtitleState {
            case .failed:
                subtitleFailureOverlay
                    .transition(.overlayFade)
            case .loading:
                subtitleLoadingHint
                    .transition(.overlayFade)
            case .unavailable:
                subtitleUnavailableHint
                    .transition(.overlayFade)
            case .idle, .loaded:
                EmptyView()
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
                Label(L10n.string("重試"), systemImage: "arrow.clockwise")
            }
            .buttonStyle(.appCompactAction(.primary))
            .accessibilityIdentifier("podcast.subtitleRetry")
        }
        .padding(.horizontal, skin.spacing.cardPadding)
    }

    /// Subtitle fetch in flight — spinner + 「字幕載入中…」hint so the empty
    /// bubble area no longer looks like a permanent silent state.
    @ViewBuilder
    private var subtitleLoadingHint: some View {
        HStack(spacing: skin.spacing.tinyGap) {
            ProgressView()
                .controlSize(.small)
                .tint(skin.palette.secondaryText)
            Text(L10n.string("字幕載入中…"))
                .font(skin.typography.caption)
                .foregroundStyle(skin.palette.secondaryText)
        }
        .padding(.horizontal, AppSpacing.s3)
        .padding(.vertical, AppSpacing.s2)
        .background(
            Capsule()
                .fill(skin.palette.cardBackground.opacity(0.92))
                .overlay(Capsule().stroke(skin.palette.cardBorder, lineWidth: 1))
        )
        .accessibilityIdentifier("podcast.subtitleLoading")
    }

    /// Episode ships no subtitle URL — explicit hint differentiates this from
    /// the loading state. Audio plays normally; nothing to retry.
    @ViewBuilder
    private var subtitleUnavailableHint: some View {
        AppStateMessageCard(
            title: "此集無逐句字幕",
            systemImage: "captions.bubble.slash",
            description: "音訊仍可正常播放",
            style: .vocab(skin)
        )
        .padding(.horizontal, skin.spacing.cardPadding)
        .accessibilityIdentifier("podcast.subtitleUnavailable")
    }
}
#endif
