import Foundation
import Testing
@testable import BooksAndVocab

struct ReaderFontSizeTextTests {
    @Test func fontSizeTextIsExactForEveryStep() {
        let range = ReaderTypographyMetrics.fontSizeRange
        let step = ReaderTypographyMetrics.fontSizeStep
        let expected = [
            "0.75x", "0.875x", "1x", "1.125x", "1.25x", "1.375x",
            "1.5x", "1.625x", "1.75x", "1.875x", "2x",
        ]
        var actual: [String] = []
        var value = range.lowerBound
        while value <= range.upperBound {
            actual.append(ReaderSettings.fontSizeText(for: value))
            value += step
        }
        #expect(actual == expected)
    }
}
