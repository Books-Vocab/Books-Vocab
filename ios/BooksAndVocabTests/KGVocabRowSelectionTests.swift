import Testing
import Foundation
@testable import BooksAndVocab

struct KGVocabRowSelectionTests {
    @Test func highlightsOnlyTheSelectedRowOutsideSelectionMode() {
        let selected = UUID()
        let other = UUID()

        #expect(KGVocabRowSelection.isHighlighted(rowID: selected, selectedRowID: selected, isSelecting: false))
        #expect(!KGVocabRowSelection.isHighlighted(rowID: other, selectedRowID: selected, isSelecting: false))
    }

    @Test func selectionModeSuppressesDetailHighlight() {
        let selected = UUID()

        #expect(!KGVocabRowSelection.isHighlighted(rowID: selected, selectedRowID: selected, isSelecting: true))
        #expect(!KGVocabRowSelection.isHighlighted(rowID: selected, selectedRowID: nil, isSelecting: false))
    }

    @Test func rowHoverAndSelectionUseTheSameCornerRadius() {
        #expect(KGVocabRowChrome.hoverCornerRadius == AppRadius.sm)
    }
}
