import XCTest

final class WordDetailFlowUITests: UITestCase {
    private enum Fixture {
        static let notebookID = "ui-word-detail-notebook"
        static let word = "ephemeral"
        static let translation = "短暫的；轉瞬即逝的"
        static let explanation = "Lasting for a very short time; describes things that fade quickly, often with a wistful, literary tone."
        static let example = "The ephemeral beauty of cherry blossoms draws crowds each spring."
        static let rootForm = "ephemeral"
        static let bookTitle = "On Writing Well"
        static let chapterTitle = "· Chapter 3 · Simplicity"
        static let syncStatus = "已同步"
        static let editedTranslation = "brief"
        static let editedExplanation = "Updated detail from Word Detail edit."
        static let pendingSyncStatus = "待同步"
    }

    override func setUpWithError() throws {
        try super.setUpWithError()
        executionTimeAllowance = 180
    }

    @MainActor
    func testWordDetailHierarchyUsesStableSelectors() throws {
        let app = launchIsolatedApp(fixtures: [.vocabulary("wordDetail")])
        let notebooks = AppPage(app: app).goToNotebooks()

        guard notebooks.waitForNotebookCard(id: Fixture.notebookID, timeout: 10) else {
            XCTFail("Word Detail fixture must materialize its notebook")
            return
        }
        notebooks.notebookCard(id: Fixture.notebookID).tapWhenReady()
        XCTAssertTrue(app.waitForNavigationToSettle())

        let vocabulary = VocabularySearchPage(app: app)
        guard vocabulary.searchField.waitUntilExists(timeout: 10) else {
            XCTFail("Word Detail fixture must materialize the vocabulary search field")
            return
        }
        vocabulary.search(Fixture.word)
        guard vocabulary.waitForRowMaterialized(word: Fixture.word, timeout: 10) else {
            XCTFail("Word Detail fixture must materialize the target word row")
            return
        }
        vocabulary.row(word: Fixture.word).tapWhenReady()

        guard vocabulary.detailHeroWord.waitUntilExists(timeout: 10) else {
            XCTFail("Selecting the target word must open Word Detail")
            return
        }
        XCTAssertEqual(vocabulary.detailHeroWord.label, Fixture.word)

        guard let hierarchy = element(
            "wordDetail.content",
            in: app,
            named: "Word Detail content hierarchy"
        ) else {
            return
        }
        guard let document = element(
            "wordDetail.document",
            below: hierarchy,
            named: "Word Detail document hierarchy"
        ), let forms = element(
            "wordDetail.forms",
            below: hierarchy,
            named: "Word Detail forms hierarchy"
        ), let metadata = element(
            "wordDetail.metadata",
            below: hierarchy,
            named: "Word Detail metadata hierarchy"
        ) else {
            return
        }

        assertExactlyOneText(Fixture.word, in: document, named: "Word Detail word")
        assertExactlyOneText(Fixture.translation, in: document, named: "Word Detail translation")
        assertExactlyOneText(Fixture.explanation, in: document, named: "Word Detail meaning")
        assertExactlyOneText(Fixture.example, in: document, named: "Word Detail example")
        assertExactlyOneText(Fixture.bookTitle, in: document, named: "Word Detail provenance book")
        assertExactlyOneText(Fixture.chapterTitle, in: document, named: "Word Detail provenance chapter")
        assertExactlyOneText(Fixture.rootForm, in: forms, named: "Word Detail root form")
        assertExactlyOneText(Fixture.syncStatus, in: metadata, named: "Word Detail sync metadata")

        XCTAssertLessThan(
            document.frame.minY,
            forms.frame.minY,
            "Word Detail forms must follow the document content"
        )
        XCTAssertLessThan(
            forms.frame.minY,
            metadata.frame.minY,
            "Word Detail metadata must follow the forms section"
        )
        captureStep("word-detail-hierarchy", app: app)
    }

    @MainActor
    func testWordDetailEditRefreshesPresentationAndKeepsPendingSync() throws {
        let app = launchIsolatedApp(fixtures: [.vocabulary("wordDetail")])
        let notebooks = AppPage(app: app).goToNotebooks()

        guard notebooks.waitForNotebookCard(id: Fixture.notebookID, timeout: 10) else {
            XCTFail("Word Detail fixture must materialize its notebook")
            return
        }
        notebooks.notebookCard(id: Fixture.notebookID).tapWhenReady()
        XCTAssertTrue(app.waitForNavigationToSettle())

        let vocabulary = VocabularySearchPage(app: app)
        guard vocabulary.searchField.waitUntilExists(timeout: 10) else {
            XCTFail("Word Detail fixture must materialize the vocabulary search field")
            return
        }
        vocabulary.search(Fixture.word)
        guard vocabulary.waitForRowMaterialized(word: Fixture.word, timeout: 10) else {
            XCTFail("Word Detail fixture must materialize the target word row")
            return
        }
        vocabulary.row(word: Fixture.word).tapWhenReady()

        guard vocabulary.detailHeroWord.waitUntilExists(timeout: 10) else {
            XCTFail("Selecting the target word must open Word Detail")
            return
        }

        guard element("wordDetail.document", in: app, named: "Word Detail edit document") != nil else {
            return
        }
        guard let editButton = app.buttons
            .matching(NSPredicate(format: "label == %@", "編輯"))
            .exactlyOneElement(timeout: 10, named: "Word Detail edit button") else {
            return
        }
        editButton.tapWhenReady()

        let editors = app.textViews
        let translationEditor = editors.element(boundBy: 0)
        let explanationEditor = editors.element(boundBy: 1)
        guard translationEditor.waitUntilExists(timeout: 10),
              explanationEditor.waitUntilExists(timeout: 10) else {
            XCTFail("Word Detail edit sheet must expose translation and explanation editors")
            return
        }
        XCTAssertEqual(translationEditor.value as? String, Fixture.translation)
        XCTAssertEqual(explanationEditor.value as? String, Fixture.explanation)

        let editedTranslation = appendText(
            " \(Fixture.editedTranslation)",
            to: translationEditor
        )
        let editedExplanation = appendText(
            " \(Fixture.editedExplanation)",
            to: explanationEditor
        )
        XCTAssertTrue(editedTranslation.contains(Fixture.editedTranslation))
        XCTAssertTrue(editedExplanation.contains(Fixture.editedExplanation))

        guard let saveButton = app.buttons
            .matching(NSPredicate(format: "label == %@", "儲存"))
            .exactlyOneElement(timeout: 10, named: "Word Detail edit save button") else {
            return
        }
        saveButton.tapWhenReady()
        XCTAssertTrue(translationEditor.waitUntilGone(timeout: 10))

        guard let refreshedDocument = element(
            "wordDetail.document",
            in: app,
            named: "Word Detail refreshed document"
        ), let metadata = element(
            "wordDetail.metadata",
            in: app,
            named: "Word Detail refreshed metadata"
        ) else {
            return
        }
        assertExactlyOneText(
            editedTranslation,
            in: refreshedDocument,
            named: "Word Detail refreshed translation"
        )
        assertExactlyOneText(
            editedExplanation,
            in: refreshedDocument,
            named: "Word Detail refreshed explanation"
        )
        assertExactlyOneText(
            Fixture.pendingSyncStatus,
            in: metadata,
            named: "Word Detail pending sync metadata"
        )
        captureStep("word-detail-edit-refresh", app: app)
    }

    private func appendText(_ text: String, to editor: XCUIElement) -> String {
        editor.tapWhenReady()
        editor.typeText(text)
        return editor.value as? String ?? ""
    }

    private func element(
        _ identifier: String,
        in app: XCUIApplication,
        named name: String
    ) -> XCUIElement? {
        app.descendants(matching: .any)
            .matching(identifier: identifier)
            .exactlyOneElement(timeout: 10, named: name)
    }

    private func element(
        _ identifier: String,
        below parent: XCUIElement,
        named name: String
    ) -> XCUIElement? {
        parent.descendants(matching: .any)
            .matching(identifier: identifier)
            .exactlyOneElement(timeout: 10, named: name)
    }

    private func assertExactlyOneText(
        _ expected: String,
        in container: XCUIElement,
        named name: String
    ) {
        guard let text = container.staticTexts
            .matching(NSPredicate(format: "label == %@", expected))
            .exactlyOneElement(timeout: 10, named: name) else {
            return
        }
        XCTAssertEqual(text.label, expected, "(name) must expose the complete fixture value")
    }
}
