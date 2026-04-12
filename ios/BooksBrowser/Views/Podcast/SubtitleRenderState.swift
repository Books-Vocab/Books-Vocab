import Foundation

/// Pre-computed render state for the current subtitle, derived from
/// PodcastSentence + PodcastSubtitleCue.  Views consume this struct
/// instead of reaching into raw engine objects.
struct SubtitleRenderState: Equatable {
    struct Word: Identifiable, Equatable {
        let id: Int
        let text: String
    }

    let sentenceId: Int
    let sentenceText: String
    let speaker: String
    let speakerIndex: Int?
    let words: [Word]

    /// Build render state from current sentence + cue.
    static func from(
        sentence: PodcastSentence,
        cue: PodcastSubtitleCue?,
        hostNames: [String]
    ) -> SubtitleRenderState {
        let speakerIdx = hostNames.firstIndex(of: sentence.speaker)
        let wordTexts = sentence.text.split(separator: " ").map(String.init)
        let wordModels = wordTexts.enumerated().map { idx, text in
            Word(id: idx, text: text)
        }
        return SubtitleRenderState(
            sentenceId: sentence.id,
            sentenceText: sentence.text,
            speaker: sentence.speaker,
            speakerIndex: speakerIdx,
            words: wordModels
        )
    }
}
