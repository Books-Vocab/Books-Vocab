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

    @Test func rowHoverAndSelectionUseTheSameRoundness() {
        // hover tint 的 modifier 預設也是 control —— 兩層若各自取值就會在同一列上畫出兩種圓角。
        #expect(KGVocabRowChrome.hoverRoundness == AppRoundness.control)
    }
}
