#if os(iOS)
import SwiftUI

struct PodcastSubtitleView: View {
    @ObserveInjection private var inject
    let viewModel: PodcastPlayerViewModel
    let subtitleSize: PodcastSubtitleSize
    let initialScrollPositionResolved: Bool
    /// 詞庫已查詞集，驅動字幕詞庫螢光筆（A 方案）。由 PodcastPlayerView 注入。
    let lookedUpWords: Set<String>
    /// Re-runs only the subtitle fetch — wired to the inline failure retry.
    var onRetrySubtitle: () -> Void = {}

    @Environment(\.appSkin) private var skin
    @Environment(\.readerSettings) private var readerSettings

    var body: some View {
        ZStack {
            PodcastSentenceLevelView(
                sentences: viewModel.visibleSentences,
                renderState: viewModel.renderState,
                liveAnchor: viewModel.liveAnchor,
                duration: viewModel.duration,
                isPlaying: viewModel.state == .playing,
                hostNames: viewModel.hostNames,
                subtitleSize: subtitleSize,
                initialScrollPositionResolved: initialScrollPositionResolved,
                scrollLeadId: viewModel.scrollLeadSentenceId,
                lookedUpWords: lookedUpWords,
                highlightPreferences: readerSettings.vocabHighlightPreferences,
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
            title: L10n.string("podcast.subtitle.loadFailed.title"),
            systemImage: "captions.bubble",
            description: L10n.string("podcast.subtitle.loadFailed.description"),
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
            Text(L10n.string("podcast.subtitle.loading.hint"))
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
            title: L10n.string("podcast.subtitle.unavailable.title"),
            systemImage: "captions.bubble.slash",
            description: L10n.string("podcast.subtitle.unavailable.description"),
            style: .vocab(skin)
        )
        .padding(.horizontal, skin.spacing.cardPadding)
        .accessibilityIdentifier("podcast.subtitleUnavailable")
    }
}
#endif
