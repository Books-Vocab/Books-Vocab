import SwiftUI

struct PodcastSubtitleView: View {
    let viewModel: PodcastPlayerViewModel
    @Environment(\.vocabSkin) private var skin

    var body: some View {
        Group {
            switch viewModel.displayMode {
            case .wordLevel:
                if let rs = viewModel.renderState {
                    PodcastWordLevelView(
                        renderState: rs,
                        highlightedWordIndex: viewModel.highlightedWordIndex,
                        hostNames: viewModel.hostNames,
                        onWordTap: viewModel.handleWordTap
                    )
                    .frame(maxHeight: .infinity)
                } else {
                    placeholder
                }
            case .sentenceLevel:
                PodcastSentenceLevelView(
                    sentences: viewModel.visibleSentences,
                    renderState: viewModel.renderState,
                    highlightedWordIndex: viewModel.highlightedWordIndex,
                    hostNames: viewModel.hostNames,
                    onSentenceTap: { viewModel.seek(to: $0.startTime) },
                    onWordTap: viewModel.handleWordTap
                )
            }
        }
    }

    @ViewBuilder
    private var placeholder: some View {
        Text("—")
            .font(skin.typography.body)
            .foregroundStyle(skin.palette.tertiaryText)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
