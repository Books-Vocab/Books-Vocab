import XCTest

final class BookshelfAccessibilityUITests: UITestCase {
    @MainActor
    func testBookCardAnnouncesReadingProgressAlongsideIdentity() throws {
        let app = launchIsolatedApp(fixtures: [.bookshelf("with_books_library")])
        // ContentView starts on `.bookshelf`; do not tap the already-selected tab
        // while the fixture-backed shell is still becoming hittable.
        let bookshelf = BookshelfPage(app: app)
        XCTAssertTrue(
            bookshelf.anyBookCard.waitUntilExists(timeout: 10),
            "with_books_library fixture must render book cards"
        )

        let cards = app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier BEGINSWITH[c] %@", "book.card."))
            .allElementsBoundByIndex
        guard let atomicHabits = cards.first(where: { $0.label.contains("Atomic Habits") }) else {
            XCTFail("fixture must render the Atomic Habits book card")
            return
        }

        XCTAssertTrue(atomicHabits.label.contains("James Clear"))
        let accessibilityValue = (atomicHabits.value as? String) ?? ""
        XCTAssertTrue(accessibilityValue.contains("72%"), "expected 72% in accessibility value, got: \(accessibilityValue)")
        XCTAssertGreaterThan(accessibilityValue.count, "72%".count, "progress value must include localized progress semantics")
    }
}
