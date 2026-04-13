import Foundation

/// Pre-computed render state for the current subtitle sentence.
/// Built once per sentence change (~0.2Hz), NOT per frame.
struct SubtitleRenderState: Equatable {
    struct Word: Identifiable, Equatable {
        let id: Int
        let text: String
        let normalizedText: String  // lowercased + punctuation trimmed for highlight matching
    }

    let sentenceId: Int
    let sentenceText: String
    let speaker: String
    let speakerIndex: Int?
    let words: [Word]

    /// Convenience initializer from sentence + host names.
    init(from sentence: PodcastSentence, hostNames: [String]) {
        self.sentenceId = sentence.id
        self.sentenceText = sentence.text
        self.speaker = sentence.speaker
        self.speakerIndex = hostNames.firstIndex(of: sentence.speaker)

        // Compact SRT: sentence.words is already 1 cue = 1 word, perfect 1:1 mapping.
        self.words = sentence.words.enumerated().map { idx, cue in
            Word(
                id: idx,
                text: cue.word,
                normalizedText: cue.word.lowercased().trimmingCharacters(in: .punctuationCharacters)
            )
        }
    }

    /// Full initializer (used by factory method).
    init(sentenceId: Int, sentenceText: String, speaker: String, speakerIndex: Int?, words: [Word]) {
        self.sentenceId = sentenceId
        self.sentenceText = sentenceText
        self.speaker = speaker
        self.speakerIndex = speakerIndex
        self.words = words
    }

    /// Build from sentence + cue (backward compat with views).
    static func from(
        sentence: PodcastSentence,
        cue: PodcastSubtitleCue?,
        hostNames: [String]
    ) -> SubtitleRenderState {
        SubtitleRenderState(from: sentence, hostNames: hostNames)
    }

    /// O(n) once per sentence, but called rarely (~0.2Hz).
    func highlightIndex(for normalizedWord: String) -> Int {
        words.firstIndex { $0.normalizedText == normalizedWord } ?? -1
    }
}
