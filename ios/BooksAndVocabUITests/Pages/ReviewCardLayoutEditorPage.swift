import XCTest

/// Page Object for `ReviewCardLayoutEditor` — the SAME view behind both entry
/// points (the review toolbar sheet and Settings ▸ 偏好 ▸ 複習卡片), so one page
/// object drives either route.
///
/// 每個方向（recognition / production）只有一個二選一：正常 / 精簡
/// （APP-20260808-7f0f3a）。逐欄位 toggle 與正面/背面 picker 已退場。
struct ReviewCardLayoutEditorPage {
    let app: XCUIApplication

    /// `ReviewCardLayoutPreset.allCases` 的順序：0 = 正常，1 = 精簡。
    enum PresetIndex {
        static let standard = 0
        static let compact = 1
    }

    // MARK: - Chrome

    var resetMenu: XCUIElement { element("reviewCardLayout.resetMenu") }
    var resetAllItem: XCUIElement { app.buttons["reviewCardLayout.reset.all"] }

    /// Sheet-only confirmation button (absent on the pushed Settings route).
    var doneButton: XCUIElement { element("reviewCardLayout.done") }

    // MARK: - Per-direction controls

    /// `mode` ∈ recognition / production（`VocabularyCardMode.rawValue`）。
    func presetPicker(_ mode: String) -> XCUIElement {
        element("reviewCardLayout.preset.\(mode)")
    }

    /// 題目／答案列。它沒有開關就是它的契約。
    func lockedRow(_ mode: String, _ face: String) -> XCUIElement {
        element("reviewCardLayout.lockedRow.\(mode).\(face)")
    }

    /// 預覽裡的一個欄位列。存在與否＝該方向目前 preset 的結果，
    /// 是這一頁唯一語言無關、可機器斷言的訊號。
    func previewField(_ mode: String, face: String, field: String) -> XCUIElement {
        element("reviewCardLayout.previewField.\(mode).\(face).\(field)")
    }

    // MARK: - Actions

    /// Segmented controls expose their options as buttons; index 見 `PresetIndex`.
    @discardableResult
    func selectPreset(
        _ mode: String,
        index: Int,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) -> Self {
        presetPicker(mode).buttons.element(boundBy: index).tapWhenReady(file: file, line: line)
        return self
    }

    @discardableResult
    func done(file: StaticString = #filePath, line: UInt = UInt(#line)) -> TodayReviewPage {
        doneButton.tapWhenReady(file: file, line: line)
        return TodayReviewPage(app: app)
    }

    @discardableResult
    func resetAll(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        resetMenu.tapWhenReady(file: file, line: line)
        resetAllItem.tapWhenReady(file: file, line: line)
        return self
    }

    // MARK: - Waits

    func waitUntilVisible(timeout: TimeInterval = 8) -> Bool {
        presetPicker("recognition").waitUntilExists(timeout: timeout)
    }

    // MARK: - Helpers

    private func element(_ identifier: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }
}
