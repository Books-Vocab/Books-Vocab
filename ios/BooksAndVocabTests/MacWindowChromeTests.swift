import XCTest
@testable import BooksAndVocab

final class MacWindowChromeTests: XCTestCase {
    /// 尺寸 invariant:最小尺寸不得大於首發尺寸,且皆為正。
    /// 守住未來誤改常數導致「首發即小於最小」的非法狀態。
    func testDefaultSizeNotSmallerThanMinimum() {
        XCTAssertGreaterThan(MacWindowChrome.minimumSize.width, 0)
        XCTAssertGreaterThan(MacWindowChrome.minimumSize.height, 0)
        XCTAssertGreaterThanOrEqual(MacWindowChrome.defaultSize.width, MacWindowChrome.minimumSize.width)
        XCTAssertGreaterThanOrEqual(MacWindowChrome.defaultSize.height, MacWindowChrome.minimumSize.height)
    }

    /// 最小尺寸需足以容納 regular split(LayoutMode.contentMaxWidth 720 + sidebar)。
    /// 防止把視窗縮到 compact 致 Workstream D 的 split 崩成單欄。
    func testMinimumWidthAccommodatesRegularLayout() {
        XCTAssertGreaterThanOrEqual(MacWindowChrome.minimumSize.width, 720)
    }
}
