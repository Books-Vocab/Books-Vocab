#if os(iOS)
import SwiftUI
import Testing
@testable import BooksAndVocab

struct NotebookEditPickerTests {
    @Test func colorAndPatternTargetsMeetHIGMinimum() {
        #expect(NotebookEditPickerMetrics.hitTarget >= 44)
        // 視覺色票可以比命中區小，但絕不可大於它，否則 frame(min:) 撐開的是視覺而非命中。
        #expect(NotebookEditPickerMetrics.swatchDiameter <= NotebookEditPickerMetrics.hitTarget)
    }

    @Test func selectionTraitMarksOnlyTheSelectedOption() {
        #expect(NotebookEditPickerMetrics.accessibilityTraits(isSelected: true).contains(.isSelected))
        #expect(!NotebookEditPickerMetrics.accessibilityTraits(isSelected: false).contains(.isSelected))
    }
}
#endif
