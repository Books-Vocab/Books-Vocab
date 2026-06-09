import XCTest

extension XCUIElement {
    /// Tap after waiting for existence, with a descriptive failure message.
    @discardableResult
    func tapWhenReady(timeout: TimeInterval = 5, file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        XCTAssertTrue(
            waitForExistence(timeout: timeout),
            "Expected element to exist before tap: \(self.description)",
            file: file, line: line
        )
        tap()
        return self
    }

    /// Assert existence with a clear failure message.
    func assertExists(timeout: TimeInterval = 5, file: StaticString = #filePath, line: UInt = UInt(#line)) {
        XCTAssertTrue(
            waitForExistence(timeout: timeout),
            "Expected element to exist: \(self.description)",
            file: file, line: line
        )
    }

    /// Assert non-existence after a short wait (allow animations to settle).
    func assertDoesNotExist(timeout: TimeInterval = 2, file: StaticString = #filePath, line: UInt = UInt(#line)) {
        let gone = !waitForExistence(timeout: timeout)
        XCTAssertTrue(
            gone,
            "Expected element to NOT exist: \(self.description)",
            file: file, line: line
        )
    }

    /// Swipe up until the element is hittable (useful for scrollable lists).
    func scrollIntoView(timeout: TimeInterval = 5, file: StaticString = #filePath, line: UInt = UInt(#line)) {
        let start = Date()
        while !isHittable && Date().timeIntervalSince(start) < timeout {
            swipeUp()
        }
        XCTAssertTrue(
            isHittable,
            "Element remained non-hittable after scrolling: \(self.description)",
            file: file, line: line
        )
    }
}

extension XCUIApplication {
    /// Wait for the app to idle after a navigation or animation.
    func waitForIdle(_ duration: TimeInterval = 0.5) {
        Thread.sleep(forTimeInterval: duration)
    }
}
