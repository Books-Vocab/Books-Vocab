import SwiftUI

struct PodcastSubtitleView: View {
    let viewModel: PodcastPlayerViewModel

    var body: some View {
        PodcastSentenceLevelView(
            sentences: viewModel.visibleSentences,
            renderState: viewModel.renderState,
            highlightedWordIndex: viewModel.highlightedWordIndex,
            hostNames: viewModel.hostNames,
            onSentenceTap: { viewModel.seek(to: $0.startTime) },
            onWordTap: viewModel.handleWordTap,
            onPhraseTap: viewModel.handlePhraseTap
        )
    }
}
