//
//  CollocationActionPillChromeTests.swift
//  BooksBrowserTests
//

import Testing
@testable import BooksBrowser

@Suite struct CollocationActionPillChromeTests {
    @Test func saveActionUsesVisibleCapsuleOutline() {
        #expect(CollocationActionPillChrome.strokeLineWidth >= 1)
        #expect(CollocationActionPillChrome.strokeOpacity >= 0.30)
        #expect(CollocationActionPillChrome.backgroundOpacity > 0)
        #expect(CollocationActionPillChrome.horizontalPadding >= 10)
        #expect(CollocationActionPillChrome.verticalPadding >= 5)
    }
}
