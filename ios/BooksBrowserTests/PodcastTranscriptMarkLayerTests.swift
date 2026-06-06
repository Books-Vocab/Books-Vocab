import Testing
@testable import BooksBrowser

struct PodcastTranscriptMarkLayerTests {
    @Test func vocabHighlightRendersBehindPlaybackUnderline() {
        #expect(PodcastTranscriptMarkLayer.vocabHighlight.placement == .background)
        #expect(PodcastTranscriptMarkLayer.playbackUnderline.placement == .overlay)
        #expect(PodcastTranscriptMarkLayer.vocabHighlight.zIndex < PodcastTranscriptMarkLayer.playbackUnderline.zIndex)
    }
}
