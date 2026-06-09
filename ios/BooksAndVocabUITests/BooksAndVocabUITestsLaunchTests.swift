//
//  BooksAndVocabUITestsLaunchTests.swift
//  Books & Vocab UI Tests
//
//  Created by 陳亮宇 on 2026/2/24.
//

import XCTest

final class BooksAndVocabUITestsLaunchTests: UITestCase {

    override class var runsForEachTargetApplicationUIConfiguration: Bool {
        true
    }

    @MainActor
    func testLaunch() throws {
        let app = launchApp()

        // Insert steps here to perform after app launch but before taking a screenshot,
        // such as logging into a test account or navigating somewhere in the app

        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = "Launch Screen"
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
