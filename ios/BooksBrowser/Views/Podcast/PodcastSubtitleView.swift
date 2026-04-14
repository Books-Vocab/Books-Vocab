import SwiftUI

struct PodcastSubtitleView: View {
    let viewModel: PodcastPlayerViewModel
    let subtitleSize: PodcastSubtitleSize

    var body: some View {
        PodcastSentenceLevelView(
            sentences: viewModel.visibleSentences,
            renderState: viewModel.renderState,
            highlightedWordIndex: viewModel.highlightedWordIndex,
            hostNames: viewModel.hostNames,
            subtitleSize: subtitleSize,
            onSentenceTap: { viewModel.seek(to: $0.startTime) },
            onPhraseTap: viewModel.handlePhraseTap,
            onExplainTap: viewModel.handleExplainTap
        )
    }
}
