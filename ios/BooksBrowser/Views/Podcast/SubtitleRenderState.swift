import SwiftUI

struct WordRenderItem: Identifiable, Equatable {
    let id: Int
    let text: String
    let normalizedText: String
    let isHighlightTarget: Bool
}

struct SubtitleRenderState: Equatable {
    let sentenceId: Int
    let speaker: String
    let speakerIndex: Int  // 0 for first host, 1+ for others
    let words: [WordRenderItem]
    let sentenceText: String

    init(from sentence: PodcastSentence, hostNames: [String]) {
        self.sentenceId = sentence.id
        self.speaker = sentence.speaker
        self.speakerIndex = hostNames.firstIndex(of: sentence.speaker) ?? 1
        self.sentenceText = sentence.text

        let rawWords = sentence.text.split(separator: " ").map(String.init)
        self.words = rawWords.enumerated().map { index, word in
            WordRenderItem(
                id: index,
                text: word,
                normalizedText: word.lowercased().trimmingCharacters(in: .punctuationCharacters),
                isHighlightTarget: true
            )
        }
    }

    func highlightIndex(for normalizedWord: String) -> Int {
        words.firstIndex { $0.normalizedText == normalizedWord } ?? -1
    }
}
