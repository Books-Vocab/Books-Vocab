import Foundation
import Testing
@testable import BooksAndVocab

struct SubtitleRenderStateTests {
    private func sentence() -> PodcastSentence {
        let words = ["OK", "so", "here's", "the", "thing."].enumerated().map { idx, word in
            PodcastSubtitleCue(
                id: idx,
                startTime: Double(idx),
                endTime: Double(idx + 1),
                speaker: "Maya",
                word: word
            )
        }
        return PodcastSentence(
            id: 1,
            speaker: "Maya",
            text: words.map(\.word).joined(separator: " "),
            startTime: 0,
            endTime: 5,
            words: words
        )
    }

    @Test func word_render_items_from_sentence() {
        let sentence = sentence()
        let state = SubtitleRenderState(from: sentence, hostNames: ["Maya", "Kai"])
        #expect(state.words.count == 5)
        guard state.words.count == 5 else { return }
        #expect(state.words[0].text == "OK")
        #expect(state.words[0].normalizedText == "ok")
        #expect(state.words[4].text == "thing.")
        #expect(state.words[4].normalizedText == "thing")
        #expect(state.speaker == "Maya")
    }

    @Test func highlight_index_matches_normalized() {
        let sentence = sentence()
        let state = SubtitleRenderState(from: sentence, hostNames: ["Maya", "Kai"])
        #expect(state.highlightIndex(for: "thing") == 4)
        #expect(state.highlightIndex(for: "ok") == 0)
        #expect(state.highlightIndex(for: "nonexistent") == -1)
    }

    @Test func subtitle_engine_sentence_binary_search() {
        let engine = PodcastSubtitleEngine()
        let srt = """
1
00:00:00,000 --> 00:00:01,000
[Maya] Hello world

2
00:00:01,000 --> 00:00:02,000
[Maya] How are you

3
00:00:02,000 --> 00:00:03,000
[Kai] I'm great
"""
        engine.load(srtContent: srt)

        let s1 = engine.currentSentence(at: 0.5)
        #expect(s1?.speaker == "Maya")
        #expect(s1?.text.contains("Hello") == true)

        let s3 = engine.currentSentence(at: 2.5)
        #expect(s3?.speaker == "Kai")
    }
}
