//
//  FixtureDatasetUITests.swift
//  Books & Vocab UI Tests
//
//  End-to-end proof for the `ios_test.sh --dataset <name>` chain:
//  runner env (KG_FIXTURE_DATASET_DEFLATE_B64, or legacy KG_FIXTURE_DATASET_B64)
//  → UITestLaunchConfiguration forwarding → app FixtureDatasetStore
//  → UITestFixtureSeed bookshelf seeder → rendered UI.
//
//  Without a UI World on the runner the test fails; run it via:
//      ./ops/ios_test.sh --ui --dataset marketing_demo -g FixtureDatasetUITests
//

import XCTest

final class FixtureDatasetUITests: UITestCase {
    /// Minimal mirror of `kg.fixture.dataset.v2` — enough to assert the runner
    /// injected the same required manifest shape the app consumes.
    private struct DatasetDocument: Decodable {
        struct Shelf: Decodable {
            struct Book: Decodable { let title: String }
            let books: [Book]
        }
        let schema: String
        let datasetID: String
        let bookshelf: [String: Shelf]
    }

    @MainActor
    func testBookshelfRendersDatasetOverriddenTitle() throws {
        let environment = ProcessInfo.processInfo.environment
        let data: Data
        if let deflateB64 = environment["KG_FIXTURE_DATASET_DEFLATE_B64"], !deflateB64.isEmpty {
            guard let compressed = Data(base64Encoded: deflateB64) else {
                XCTFail("KG_FIXTURE_DATASET_DEFLATE_B64 is not valid base64")
                return
            }
            data = try (compressed as NSData).decompressed(using: .zlib) as Data
        } else if let base64 = environment["KG_FIXTURE_DATASET_B64"], !base64.isEmpty {
            guard let decoded = Data(base64Encoded: base64) else {
                XCTFail("KG_FIXTURE_DATASET_B64 is not valid base64")
                return
            }
            data = decoded
        } else {
            XCTFail("missing UI World on the runner — run via ./ops/ios_test.sh --ui --dataset <name>")
            return
        }
        let document = try JSONDecoder().decode(DatasetDocument.self, from: data)
        XCTAssertEqual(document.schema, "kg.fixture.dataset.v2")
        XCTAssertFalse(document.datasetID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        guard let expectedTitle = document.bookshelf["with_books_library"]?.books.first?.title else {
            XCTFail("UI World defines no bookshelf.with_books_library entry")
            return
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
