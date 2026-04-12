import SwiftUI

struct PodcastSubtitleView: View {
    let viewModel: PodcastPlayerViewModel
    @Environment(\.vocabSkin) private var skin

    var body: some View {
        Group {
            switch viewModel.displayMode {
            case .wordLevel:
                PodcastWordLevelView(
                    sentence: viewModel.currentSentence,
                    currentCue: viewModel.currentCue,
                    hostNames: viewModel.hostNames,
                    onWordTap: viewModel.handleWordTap
                )
                .frame(maxHeight: .infinity)
            case .sentenceLevel:
                PodcastSentenceLevelView(
                    sentences: viewModel.visibleSentences,
                    currentSentenceId: viewModel.currentSentence?.id,
                    hostNames: viewModel.hostNames,
                    onSentenceTap: { viewModel.seek(to: $0.startTime) },
                    onWordTap: viewModel.handleWordTap
                )
            }
        }
    }
}
