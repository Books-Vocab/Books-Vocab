import XCTest

/// Page Object for the Today Review (flashcard) full-screen cover.
///
/// The cover hides the navigation bar (`platformHideNavigationBar`), so all
/// selectors target accessibility identifiers on the review chrome itself —
/// the previous navigation-bar-based selectors never matched this scene.
struct TodayReviewPage {
    let app: XCUIApplication

    enum CardPresentation: String {
        case natural
        case scroll
    }

    enum CardFace: String {
        case front
        case back
    }

    struct CardGeometryContract: Equatable {
        let minimumWidth: CGFloat
        let minimumHeight: CGFloat
        let expectedExpandZoneCount: Int
        let maximumBottomGap: CGFloat?

        static let compactFront = CardGeometryContract(
            minimumWidth: 280,
            minimumHeight: 100,
            expectedExpandZoneCount: 1,
            maximumBottomGap: 48
        )

        static let compactBack = CardGeometryContract(
            minimumWidth: 280,
            minimumHeight: 100,
            expectedExpandZoneCount: 0,
            maximumBottomGap: nil
        )

        static let fullFront = CardGeometryContract(
            minimumWidth: 280,
            minimumHeight: 100,
            expectedExpandZoneCount: 1,
            maximumBottomGap: 48
        )

        static let fullBack = CardGeometryContract(
            minimumWidth: 280,
            minimumHeight: 100,
            expectedExpandZoneCount: 1,
            maximumBottomGap: nil
        )
    }

    struct CardIdentity: Equatable {
        enum ReviewMode: String {
            case recognition
            case production
        }

        enum LayoutPreset: String {
            case standard
            case compact
        }

        let cardID: String
        let frontWord: String
        let mode: ReviewMode
        let preset: LayoutPreset
        let translationPrefix: String
        let minimumTranslationLength: Int
        let effectiveLayoutProfile: String

        static let p12CompactCoaxedRecognition = CardIdentity(
            cardID: "review-card-compact-coaxed",
            frontWord: "coaxed",
            mode: .recognition,
            preset: .compact,
            translationPrefix: "說服、哄勸",
            minimumTranslationLength: 180,
            effectiveLayoutProfile: "recognition:compact,production:compact"
        )

        static let p13Production = CardIdentity(
            cardID: "review-card-full-coaxed",
            frontWord: "coaxed",
            mode: .production,
            preset: .standard,
            translationPrefix: "說服；以溫和、耐心",
            minimumTranslationLength: 180,
            effectiveLayoutProfile: "recognition:standard,production:standard"
        )

        var frontRequiredFields: [String] {
            switch (mode, preset) {
            case (.production, .standard): ["partOfSpeech", "example"]
            case (.recognition, .standard), (.recognition, .compact), (.production, .compact): ["partOfSpeech"]
            }
        }

        var frontAbsentFields: [String] {
            switch preset {
            case .standard where mode == .production: ["explanation", "collocations"]
            case .standard, .compact: ["example", "explanation", "collocations"]
            }
        }

        var backRequiredFields: [String] {
            preset == .standard
                ? ["difficultyTier", "graphLinks", "example", "explanation", "collocations"]
                : ["difficultyTier", "graphLinks"]
        }

        var backAbsentFields: [String] {
            preset == .standard ? [] : ["example", "explanation", "collocations"]
        }

        func matches(_ accessibilityValue: String) -> Bool {
            let values = Dictionary(uniqueKeysWithValues: accessibilityValue.split(separator: ";").compactMap { part -> (String, String)? in
                let pieces = part.split(separator: "=", maxSplits: 1).map(String.init)
                guard pieces.count == 2 else { return nil }
                return (pieces[0], pieces[1])
            })
            guard values["cardID"] == cardID,
                  values["frontWord"] == frontWord,
                  values["mode"] == mode.rawValue,
                  values["preset"] == preset.rawValue,
                  values["layoutProfile"] == effectiveLayoutProfile,
                  let translationLength = values["translationLength"].flatMap(Int.init),
                  translationLength >= minimumTranslationLength else {
                return false
            }
            return translationPrefix.isEmpty || values["translationPrefix"]?.hasPrefix(translationPrefix) == true
        }
    }

    struct EvidenceReadinessContract: Equatable {
        let face: CardFace
        let identity: CardIdentity
        let presentation: CardPresentation
        let geometry: CardGeometryContract

        var requiredFields: [String] {
            face == .front ? identity.frontRequiredFields : identity.backRequiredFields
        }

        var absentFields: [String] {
            face == .front ? identity.frontAbsentFields : identity.backAbsentFields
        }
    }

    // MARK: - Chrome

    /// "k / N" progress capsule in the top bar — the queue-position truth.
    var progressLabel: XCUIElement {
        element("todayReview.progressLabel")
    }

    /// Top-bar xmark chrome button (L10n `vocab.chromeIcon.todayReview.close`).
    var closeButton: XCUIElement {
        element("todayReview.close")
    }

    /// Top-bar entry to the shared review-card layout editor (between autoplay
    /// and close).
    var layoutEditorButton: XCUIElement {
        element("todayReview.layoutEditor.open")
    }

    /// Autoplay play/pause control, identified by STATE rather than its localized
    /// label — `…autoplay.paused` exists only while autoplay is paused.
    var autoplayPausedButton: XCUIElement {
        element("todayReview.autoplay.paused")
    }

    var autoplayPlayingButton: XCUIElement {
        element("todayReview.autoplay.playing")
    }

    /// Top-bar autoplay toggle.
    var autoplayToggleButton: XCUIElement {
        element("todayReview.autoplayToggle")
    }

    // NOTE (measured 2026-08-06) said the front face published
    // `todayReview.card.front` on 2–3 nested ~36pt buttons, so the card box height
    // was unreadable from a UI test. That was FIXED on 2026-08-08 by `2ac7ba258`
    // (`.accessibilityElement(children: .contain)` declared before the property
    // modifiers), so `cardFront.frame` is the card box again. Geometry assertions
    // on this card are legitimate — but keep a `height >= 100` positive control:
    // if the container declaration ever regresses, the query resolves a nested
    // button and every geometry assertion silently measures the wrong element.

    // MARK: - Card

    /// Front fold surface (the tappable word side). Exists for the whole
    /// session; flipping is asserted via `cardBack` appearing, not via this.
    var cardFront: XCUIElement {
        element("todayReview.card.front")
    }

    /// Mounted back content. Only exists while the answer is revealed — the
    /// folded state holds a zero-cost stub without this identifier, so
    /// `cardBack.exists` is a REAL flip-state signal.
    var cardBack: XCUIElement {
        element("todayReview.card.back")
    }

    var frontNaturalContent: XCUIElement {
        element("todayReview.card.front.content.natural")
    }

    var frontScrollContent: XCUIElement {
        element("todayReview.card.front.content.scroll")
    }

    /// The renderer publishes exactly one of these two content selectors. They
    /// make the natural-fit versus top-anchored-scroll contract assertable without
    /// depending on localized text or screenshot pixel matching.
    var backNaturalContent: XCUIElement {
        element("todayReview.card.back.content.natural")
    }

    var backScrollContent: XCUIElement {
        element("todayReview.card.back.content.scroll")
    }

    /// Field-level selectors are deliberately stable raw-value IDs. The standard
    /// profile test uses them to prove example/explanation/collocations/graph links
    /// remain mounted on the back face, while compact remains testable by absence.
    func backField(_ rawValue: String) -> XCUIElement {
        element("todayReview.card.back.field.\(rawValue)")
    }

    /// The "tap to expand" zone below the card (front stage only). Its
    /// `frame.minY` is the top boundary of the region directly below the card
    /// region; `expandZone.minY − cardFront.maxY` is the visible gap between the
    /// card and the bottom expand hint.
    var expandZone: XCUIElement {
        element("todayReview.expandZone")
    }

    // MARK: - Toolbar

    var rememberedButton: XCUIElement {
        element("todayReview.feedback.remembered")
    }

    var forgotButton: XCUIElement {
        element("todayReview.feedback.forgot")
    }

    /// Add-link entry point on the current card's graph-link section.
    var addLinkButton: XCUIElement {
        // This element is mounted only after the reveal transition. Keep the
        // getter side-effect-free so callers can wait for the real UI state
        // before asserting singleton cardinality.
        app.descendants(matching: .any)
            .matching(identifier: "todayReview.card.addLink")
            .element
    }

    func assertAddLinkButtonIsUnique(
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        XCTAssertEqual(
            app.descendants(matching: .any)
                .matching(identifier: "todayReview.card.addLink")
                .count,
            1,
            "Today Review add-link selector must resolve exactly once",
            file: file,
            line: line
        )
    }

    func link(id: String) -> XCUIElement {
        exactlyOne("todayReview.card.link.\(id)", in: app.descendants(matching: .any))
    }

    func assertLink(
        id: String,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        let identifier = "todayReview.card.link.\(id)"
        let matches = app.descendants(matching: .any).matching(identifier: identifier)
        XCTAssertEqual(matches.count, 1, "projected link selector must resolve exactly once: \(identifier)", file: file, line: line)
        let target = link(id: id)
        XCTAssertTrue(target.waitUntilExists(timeout: 10), "projected link did not mount: \(identifier)", file: file, line: line)
        XCTAssertGreaterThan(target.frame.width, 0, "projected link has no positive width: \(identifier)", file: file, line: line)
        XCTAssertGreaterThan(target.frame.height, 0, "projected link has no positive height: \(identifier)", file: file, line: line)
    }

    func assertCardBackDoesNotExist(file: StaticString = #filePath, line: UInt = UInt(#line)) {
        XCTAssertEqual(
            elements(for: "todayReview.card.back").count,
            0,
            "Today Review back face must be absent before the capture flip",
            file: file,
            line: line
        )
    }

    func assertAutoplayPlayingDoesNotExist(file: StaticString = #filePath, line: UInt = UInt(#line)) {
        XCTAssertEqual(
            elements(for: "todayReview.autoplay.playing").count,
            0,
            "Today Review autoplay playing state must be absent",
            file: file,
            line: line
        )
    }

    // MARK: - Readers

    var progressText: String { progressLabel.label }

    /// Front card label is "複習卡片正面：<word>" (en: "Review card front: <word>");
    /// extract the word after the last colon of either kind.
    var frontWord: String {
        let label = cardFront.label
        for separator in ["：", ": "] {
            if let range = label.range(of: separator, options: .backwards) {
                return String(label[range.upperBound...])
                    .trimmingCharacters(in: .whitespaces)
            }
        }
        return label
    }

    // MARK: - Actions

    @discardableResult
    func flipCard(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        cardFront.tapWhenReady(file: file, line: line)
        return self
    }

    @discardableResult
    func tapRemembered(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        rememberedButton.tapWhenReady(file: file, line: line)
        return self
    }

    @discardableResult
    func tapForgot(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        forgotButton.tapWhenReady(file: file, line: line)
        return self
    }

    @discardableResult
    func close(file: StaticString = #filePath, line: UInt = UInt(#line)) -> NotebookPage {
        closeButton.tapWhenReady(file: file, line: line)
        return NotebookPage(app: app)
    }

    // MARK: - Assertions

    func assertIsActive(file: StaticString = #filePath, line: UInt = UInt(#line)) {
        progressLabel.assertExists(file: file, line: line)
        XCTAssertEqual(
            elements(for: "todayReview.progressLabel").count,
            1,
            "Today Review progress label must have exactly one accessibility element",
            file: file,
            line: line
        )
    }

    // MARK: - Evidence readiness

    /// Wait for the exact typed card/presentation/geometry state before taking a
    /// screenshot. The face-specific selector is part of the contract: a back
    /// capture is never certified by the front face.
    @discardableResult
    func waitForEvidenceReadiness(
        _ contract: EvidenceReadinessContract,
        timeout: TimeInterval = 8
    ) -> Bool {
        switch contract.face {
        case .front:
            return waitForFrontReadiness(
                identity: contract.identity,
                presentation: contract.presentation,
                requiredFields: contract.requiredFields,
                absentFields: contract.absentFields,
                geometry: contract.geometry,
                timeout: timeout
            )
        case .back:
            return waitForBackReadiness(
                identity: contract.identity,
                presentation: contract.presentation,
                requiredFields: contract.requiredFields,
                absentFields: contract.absentFields,
                geometry: contract.geometry,
                timeout: timeout
            )
        }
    }

    @discardableResult
    func waitForFrontReadiness(
        identity: CardIdentity,
        presentation: CardPresentation,
        requiredFields: [String],
        absentFields: [String],
        geometry: CardGeometryContract,
        timeout: TimeInterval = 8
    ) -> Bool {
        waitForCardReadiness(
            cardIdentifier: "todayReview.card.front",
            identity: identity,
            presentationIdentifier: presentation.identifier(for: "todayReview.card.front.content"),
            alternatePresentationIdentifier: presentation.alternate.identifier(for: "todayReview.card.front.content"),
            requiredFieldIdentifiers: requiredFields.map { "todayReview.card.front.field.\($0)" },
            absentFieldIdentifiers: absentFields.map { "todayReview.card.front.field.\($0)" },
            geometry: geometry,
            timeout: timeout
        )
    }

    /// Wait until the mounted back face, its chosen presentation, and every
    /// requested field are uniquely addressable before evidence capture.
    @discardableResult
    func waitForBackReadiness(
        identity: CardIdentity,
        presentation: CardPresentation,
        requiredFields: [String],
        absentFields: [String],
        geometry: CardGeometryContract,
        timeout: TimeInterval = 8
    ) -> Bool {
        waitForCardReadiness(
            cardIdentifier: "todayReview.card.back",
            identity: identity,
            presentationIdentifier: presentation.identifier(for: "todayReview.card.back.content"),
            alternatePresentationIdentifier: presentation.alternate.identifier(for: "todayReview.card.back.content"),
            requiredFieldIdentifiers: requiredFields.map { "todayReview.card.back.field.\($0)" },
            absentFieldIdentifiers: absentFields.map { "todayReview.card.back.field.\($0)" },
            geometry: geometry,
            timeout: timeout
        )
    }

    @discardableResult
    func waitForUnique(_ identifier: String, timeout: TimeInterval = 8) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            let matches = elements(for: identifier).allElementsBoundByIndex
            if matches.count == 1, matches[0].exists { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        let matches = elements(for: identifier).allElementsBoundByIndex
        return matches.count == 1 && matches[0].exists
    }

    // MARK: - Waits

    /// Poll-based label wait that re-resolves the element query each iteration.
    ///
    /// `waitUntilLabelContains` (XCTNSPredicateExpectation) can keep reading a
    /// STALE accessibility snapshot while the grading fling / card-advance
    /// animations run — observed timing out on "3 / 8" while the live label
    /// already showed it. Explicit RunLoop polling is the same pattern
    /// `PodcastPlaybackPerfUITests` uses for its elapsed-time clock.
    func waitUntilLabel(
        of element: XCUIElement,
        contains substring: String,
        timeout: TimeInterval = 8
    ) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if element.exists, element.label.contains(substring) { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.25))
        }
        return element.exists && element.label.contains(substring)
    }

    /// Wait until the top-bar progress capsule reads `"k / N"`-style `text`.
    func waitForProgress(_ text: String, timeout: TimeInterval = 8) -> Bool {
        waitUntilLabel(of: progressLabel, contains: text, timeout: timeout)
    }

    // MARK: - Helpers

    private func waitForCardReadiness(
        cardIdentifier: String,
        identity: CardIdentity,
        presentationIdentifier: String,
        alternatePresentationIdentifier: String,
        requiredFieldIdentifiers: [String],
        absentFieldIdentifiers: [String],
        geometry: CardGeometryContract,
        timeout: TimeInterval
    ) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if cardIsCanonical(cardIdentifier, identity: identity),
               cardMatchesGeometry(cardIdentifier, geometry: geometry),
               scopedPresentationAnchor(cardIdentifier, presentationIdentifier),
               scopedCount(cardIdentifier, alternatePresentationIdentifier) == 0,
               requiredFieldIdentifiers.allSatisfy({ scopedRequiredField(cardIdentifier, $0) }),
               absentFieldIdentifiers.allSatisfy({ scopedCount(cardIdentifier, $0) == 0 }) {
                return true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }

        return cardIsCanonical(cardIdentifier, identity: identity)
            && cardMatchesGeometry(cardIdentifier, geometry: geometry)
            && scopedPresentationAnchor(cardIdentifier, presentationIdentifier)
            && scopedCount(cardIdentifier, alternatePresentationIdentifier) == 0
            && requiredFieldIdentifiers.allSatisfy({ scopedRequiredField(cardIdentifier, $0) })
            && absentFieldIdentifiers.allSatisfy({ scopedCount(cardIdentifier, $0) == 0 })
    }

    private func cardIsCanonical(_ identifier: String, identity: CardIdentity) -> Bool {
        let matching = elements(for: identifier).allElementsBoundByIndex
        guard matching.count == 1 else { return false }
        let card = matching[0]
        guard card.exists else { return false }
        return (card.value as? String).map(identity.matches) == true
    }

    private func cardMatchesGeometry(_ identifier: String, geometry: CardGeometryContract) -> Bool {
        let matching = elements(for: identifier).allElementsBoundByIndex
        guard matching.count == 1 else { return false }
        let card = matching[0]
        let frame = card.frame
        guard card.exists,
              frame.width >= geometry.minimumWidth,
              frame.height >= geometry.minimumHeight,
              frame.minX.isFinite,
              frame.minY.isFinite,
              frame.maxX.isFinite,
              frame.maxY.isFinite else {
            return false
        }
        let expandMatches = elements(for: "todayReview.expandZone").allElementsBoundByIndex
        guard expandMatches.count == geometry.expectedExpandZoneCount else { return false }
        guard let maximumBottomGap = geometry.maximumBottomGap else { return true }
        guard expandMatches.count == 1, expandMatches[0].exists else { return false }
        let expandFrame = expandMatches[0].frame
        let bottomGap = expandFrame.minY - frame.maxY
        return expandFrame.minY.isFinite
            && expandFrame.maxY.isFinite
            && bottomGap.isFinite
            && bottomGap >= 0
            && bottomGap <= maximumBottomGap
    }

    /// The review deck intentionally keeps two non-interactive preview cards
    /// mounted behind the interactive card. Their identifiers are valid but
    /// must not participate in the active-card evidence contract.
    private func scopedExactlyOne(_ cardIdentifier: String, _ identifier: String) -> Bool {
        let matching = scopedElements(cardIdentifier, identifier).allElementsBoundByIndex
        return matching.count == 1 && matching[0].exists
    }

    /// Most fields are singleton anchors. Collocations are a real collection:
    /// one accessibility identifier is published for each visible item, so the
    /// readiness contract must prove at least one mounted item without
    /// collapsing the collection into a fake singleton.
    private func scopedRequiredField(_ cardIdentifier: String, _ identifier: String) -> Bool {
        let matching = scopedElements(cardIdentifier, identifier).allElementsBoundByIndex
        guard identifier.hasSuffix(".collocations") else {
            return matching.count == 1 && matching[0].exists
        }
        return matching.contains { $0.exists && !$0.frame.isEmpty }
    }

    private func scopedPresentationAnchor(_ cardIdentifier: String, _ identifier: String) -> Bool {
        let anchors = scopedElements(cardIdentifier, identifier).allElementsBoundByIndex.filter { element in
            element.exists && element.frame.width <= 1.5 && element.frame.height <= 1.5
        }
        return anchors.count == 1
    }

    private func scopedCount(_ cardIdentifier: String, _ identifier: String) -> Int {
        scopedElements(cardIdentifier, identifier).allElementsBoundByIndex.count
    }

    private func scopedElements(_ cardIdentifier: String, _ identifier: String) -> XCUIElementQuery {
        let cards = elements(for: cardIdentifier).allElementsBoundByIndex
        guard cards.count == 1 else {
            return app.descendants(matching: .any).matching(identifier: "__invalid-card-scope__")
        }
        return cards[0].descendants(matching: .any).matching(identifier: identifier)
    }

    private func elements(for identifier: String) -> XCUIElementQuery {
        app.descendants(matching: .any).matching(identifier: identifier)
    }

    private func element(_ identifier: String) -> XCUIElement {
        exactlyOne(identifier, in: app.descendants(matching: .any))
    }

    private func exactlyOne(_ identifier: String, in query: XCUIElementQuery) -> XCUIElement {
        let matches = query.matching(identifier: identifier)
        XCTAssertEqual(matches.count, 1, "P1 selector must resolve exactly once: \(identifier)")
        return matches.element
    }
}

private extension TodayReviewPage.CardPresentation {
    var alternate: Self { self == .natural ? .scroll : .natural }

    func identifier(for prefix: String) -> String {
        "\(prefix).\(rawValue)"
    }
}
