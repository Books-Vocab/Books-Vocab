//
//  FixtureDatasetUITests.swift
//  Books & Vocab UI Tests
//
//  End-to-end proof for the `ios_test.sh --dataset <name>` chain:
//  runner env (KG_FIXTURE_DATASET_B64) → UITestLaunchConfiguration forwarding
//  → app FixtureDatasetStore → UITestFixtureSeed bookshelf seeder → rendered UI.
//
//  Without a dataset on the runner the test skips, so the default --ui sweep
//  stays green; run it for real via:
//      ./ops/ios_test.sh --ui --dataset marketing_demo -g FixtureDatasetUITests
//

import XCTest

final class FixtureDatasetUITests: UITestCase {
    /// Minimal mirror of `kg.fixture.dataset.v1` — just enough to learn what
    /// the injected dataset promises for the bookshelf fixture, so the
    /// assertion adapts to whichever dataset the runner was given.
    private struct DatasetDocument: Decodable {
        struct Shelf: Decodable {
            struct Book: Decodable { let title: String }
            let books: [Book]
        }
        let bookshelf: [String: Shelf]?
    }

    @MainActor
    func testBookshelfRendersDatasetOverriddenTitle() throws {
        guard let base64 = ProcessInfo.processInfo.environment["KG_FIXTURE_DATASET_B64"],
              !base64.isEmpty else {
            throw XCTSkip("no fixture dataset on the runner — run via ./ops/ios_test.sh --ui --dataset <name>")
        }
        guard let data = Data(base64Encoded: base64) else {
            XCTFail("KG_FIXTURE_DATASET_B64 is not valid base64")
            return
        }
        let document = try JSONDecoder().decode(DatasetDocument.self, from: data)
        guard let expectedTitle = document.bookshelf?["with_books_library"]?.books.first?.title else {
            throw XCTSkip("dataset defines no bookshelf.with_books_library entry — nothing to assert")
        }

        let app = launchIsolatedApp(fixtures: [.bookshelf("with_books_library")])
        let shell = AppPage(app: app)
        let bookshelf = shell.goToBookshelf()
        guard bookshelf.anyBookCard.waitUntilExists(timeout: 10) else {
            XCTFail("bookshelf fixture (with_books_library) should render at least one book card")
            return
        }
        XCTAssertTrue(
            app.staticTexts[expectedTitle].waitUntilExists(timeout: 5),
            "dataset-overridden book title '\(expectedTitle)' should render in the bookshelf"
        )
    }
}
