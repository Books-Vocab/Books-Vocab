import Testing
@testable import BooksAndVocab

struct PodcastTranscriptMarkLayerTests {
    @Test func vocabHighlightRendersBehindPlaybackUnderline() {
        #expect(PodcastTranscriptMarkLayer.vocabHighlight.placement == .background)
        #expect(PodcastTranscriptMarkLayer.playbackUnderline.placement == .overlay)
        #expect(PodcastTranscriptMarkLayer.vocabHighlight.zIndex < PodcastTranscriptMarkLayer.playbackUnderline.zIndex)
    }
}
