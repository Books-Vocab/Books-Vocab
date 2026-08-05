import XCTest

/// Page Object for `ReviewCardLayoutEditor` — the SAME view behind both entry
/// points (the review toolbar sheet and Settings ▸ 偏好 ▸ 複習卡片), so one page
/// object drives either route.
struct ReviewCardLayoutEditorPage {
    let app: XCUIApplication

    // MARK: - Chrome

    var modePicker: XCUIElement { element("reviewCardLayout.modePicker") }
    var facePicker: XCUIElement { element("reviewCardLayout.facePicker") }
    var preview: XCUIElement { element("reviewCardLayout.preview") }
    var resetMenu: XCUIElement { element("reviewCardLayout.resetMenu") }
    var resetCurrentModeItem: XCUIElement { app.buttons["reviewCardLayout.reset.currentMode"] }
    var resetAllItem: XCUIElement { app.buttons["reviewCardLayout.reset.all"] }

    /// The prompt/answer row. It carries no switch — that is the contract.
    var lockedRow: XCUIElement { element("reviewCardLayout.lockedRow") }

    /// Sheet-only confirmation button (absent on the pushed Settings route).
    var doneButton: XCUIElement { element("reviewCardLayout.done") }

    // MARK: - Field toggles

    /// `rawValue` ∈ partOfSpeech / difficultyTier / example / explanation /
    /// collocations / graphLinks.
    func toggle(_ rawValue: String) -> XCUIElement {
        app.switches["reviewCardLayout.toggle.\(rawValue)"]
    }

    func isOn(_ rawValue: String) -> Bool {
        (toggle(rawValue).value as? String) == "1"
    }

    // MARK: - Actions

    /// Segmented controls expose their options as buttons; index 0 = 正面 / 辨識.
    @discardableResult
    func selectFace(_ index: Int, file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        facePicker.buttons.element(boundBy: index).tapWhenReady(file: file, line: line)
        return self
    }

    @discardableResult
    func selectMode(_ index: Int, file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        modePicker.buttons.element(boundBy: index).tapWhenReady(file: file, line: line)
        return self
    }

    @discardableResult
    func setField(_ rawValue: String, on: Bool, file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        guard isOn(rawValue) != on else { return self }
        toggle(rawValue).tapWhenReady(file: file, line: line)
        return self
    }

    @discardableResult
    func done(file: StaticString = #filePath, line: UInt = UInt(#line)) -> TodayReviewPage {
        doneButton.tapWhenReady(file: file, line: line)
        return TodayReviewPage(app: app)
    }

    // MARK: - Waits

    func waitUntilVisible(timeout: TimeInterval = 8) -> Bool {
        facePicker.waitUntilExists(timeout: timeout)
    }

    // MARK: - Helpers

    private func element(_ identifier: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }
}
