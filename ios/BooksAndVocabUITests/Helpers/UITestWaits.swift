import XCTest

enum UITestWaits {
    @discardableResult
    static func wait(
        for predicate: NSPredicate,
        on object: Any,
        timeout: TimeInterval,
        pollInterval: TimeInterval = 0.1
    ) -> Bool {
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: object)
        expectation.expectationDescription = predicate.predicateFormat
        let result = XCTWaiter.wait(for: [expectation], timeout: timeout)
        if result != .completed && pollInterval > 0 {
            RunLoop.current.run(until: Date().addingTimeInterval(pollInterval))
        }
        return result == .completed
    }
}

extension XCUIElement {
    @discardableResult
    func waitUntilExists(timeout: TimeInterval = 5) -> Bool {
        UITestWaits.wait(for: NSPredicate(format: "exists == true"), on: self, timeout: timeout)
    }

    @discardableResult
    func waitUntilHittable(timeout: TimeInterval = 5) -> Bool {
        UITestWaits.wait(for: NSPredicate(format: "exists == true AND hittable == true"), on: self, timeout: timeout)
    }

    @discardableResult
    func waitUntilGone(timeout: TimeInterval = 5) -> Bool {
        UITestWaits.wait(for: NSPredicate(format: "exists == false"), on: self, timeout: timeout)
    }

    @discardableResult
    func waitUntilLabelContains(_ substring: String, timeout: TimeInterval = 5) -> Bool {
        UITestWaits.wait(
            for: NSPredicate(format: "exists == true AND label CONTAINS[c] %@", substring),
            on: self,
            timeout: timeout
        )
    }

    func assertExists(timeout: TimeInterval = 5, file: StaticString = #filePath, line: UInt = UInt(#line)) {
        XCTAssertTrue(waitUntilExists(timeout: timeout), "Expected element to exist: \(self.description)", file: file, line: line)
    }

    func assertDoesNotExist(timeout: TimeInterval = 2, file: StaticString = #filePath, line: UInt = UInt(#line)) {
        XCTAssertTrue(waitUntilGone(timeout: timeout), "Expected element to NOT exist: \(self.description)", file: file, line: line)
    }

    @discardableResult
    func tapWhenReady(timeout: TimeInterval = 5, file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        XCTAssertTrue(waitUntilHittable(timeout: timeout), "Expected element to be hittable before tap: \(self.description)", file: file, line: line)
        tap()
        return self
    }

    func scrollIntoView(timeout: TimeInterval = 5, file: StaticString = #filePath, line: UInt = UInt(#line)) {
        let deadline = Date().addingTimeInterval(timeout)
        while !isHittable && Date() < deadline {
            swipeUp()
        }
        XCTAssertTrue(isHittable, "Element remained non-hittable after scrolling: \(self.description)", file: file, line: line)
    }
}

extension XCUIApplication {
    @discardableResult
    func waitForNavigationToSettle(timeout: TimeInterval = 5) -> Bool {
        let navigationBar = navigationBars.firstMatch
        let settled = UITestWaits.wait(
            for: NSPredicate(format: "exists == true"),
            on: navigationBar,
            timeout: min(timeout, 2)
        )
        if settled {
            RunLoop.current.run(until: Date().addingTimeInterval(0.35))
        }
        return settled
    }
}
