import Testing
import CoreGraphics
@testable import BooksAndVocab

struct WordDetailInspectorMetricsTests {
    @Test func contentWidthClampsForDesktopInspector() {
        #expect(WordDetailInspectorMetrics.contentWidth(containerWidth: 240) == 320)
        #expect(WordDetailInspectorMetrics.contentWidth(containerWidth: 480) == 480)
        #expect(WordDetailInspectorMetrics.contentWidth(containerWidth: 900) == 640)
    }
}
