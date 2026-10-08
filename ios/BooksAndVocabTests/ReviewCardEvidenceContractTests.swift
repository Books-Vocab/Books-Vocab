import Foundation
import Testing
@testable import BooksAndVocab

/// Source-level contract for the P12/P13 review-card evidence path (Issue #2114).
///
/// A P12/P13 screenshot is evidence only if the page objects behind it resolve
/// exactly one scoped element and wait on typed readiness. When either property
/// regresses the UI tests usually keep passing (a `firstMatch` still "finds" a
/// card), so the rules live here, in the unit target CI runs on every iOS change.
/// This replaces `ios/StaticTests/review_card_evidence_contract.swift`, which no
/// runner executed and which had stopped matching the page objects. The fixture
/// side (canonical seeds, capture identities, asset IDs) is pinned by
/// `ops/tests/test_ui_world_manifest.py`.
///
/// A deliberate change to an evidence accessor updates the tables in
/// `ReviewCardEvidenceRules` in the same change. `everyRuleFiresOnAnInjectedViolation`
/// keeps each rule from passing vacuously.
struct ReviewCardEvidenceContractTests {
    @Test func evidenceSourcesHaveNoImplicitFirstMatchSleepOrSwallowedFailure() throws {
        let violations = try ReviewCardEvidenceRules.forbiddenTokens(in: ReviewCardEvidenceSources.load())
        #expect(violations.isEmpty, "\(violations.joined(separator: "\n"))")
    }

    @Test func positionalPicksStayInQueryOnlyHelpers() throws {
        let violations = try ReviewCardEvidenceRules.positionalPicks(in: ReviewCardEvidenceSources.load())
        #expect(violations.isEmpty, "\(violations.joined(separator: "\n"))")
    }

    @Test func evidenceAccessorsFailClosedOnCardinalityDrift() throws {
        let violations = try ReviewCardEvidenceRules.cardinality(in: ReviewCardEvidenceSources.load())
        #expect(violations.isEmpty, "\(violations.joined(separator: "\n"))")
    }

    @Test func everyDeclaredCaptureIsTakenAfterTypedReadiness() throws {
        let violations = try ReviewCardEvidenceRules.captureFlow(in: ReviewCardEvidenceSources.load())
        #expect(violations.isEmpty, "\(violations.joined(separator: "\n"))")
    }

    /// An absent-field check on a misspelled field always counts zero, so a typo
    /// would "prove" a field hidden without looking at it.
    @Test func readinessFieldNamesAreProductionFields() throws {
        let violations = try ReviewCardEvidenceRules.fieldNames(in: ReviewCardEvidenceSources.load())
        #expect(violations.isEmpty, "\(violations.joined(separator: "\n"))")
    }

    @Test func commentsNeitherTriggerNorHideAViolation() throws {
        let sources = try ReviewCardEvidenceSources.load()

        let documented = sources.appending("""

            // firstMatch sleep( element(boundBy: 0) XCTSkip try? attachText
            /* nested /* firstMatch */ Thread.sleep(forTimeInterval: 1) */
            """, to: .todayReviewPage)
        let documentedViolations = try ReviewCardEvidenceRules.all(in: documented)
        #expect(documentedViolations.isEmpty, "\(documentedViolations.joined(separator: "\n"))")

        let hidden = sources.appending("""

            let url = "http://127.0.0.1:9"; _ = app.buttons.firstMatch
            """, to: .captureTests)
        let hiddenViolations = try ReviewCardEvidenceRules.forbiddenTokens(in: hidden)
        #expect(!hiddenViolations.isEmpty, "code after a string containing // was treated as a comment")
    }

    @Test func everyRuleFiresOnAnInjectedViolation() throws {
        let sources = try ReviewCardEvidenceSources.load()
        let baseline = try ReviewCardEvidenceRules.all(in: sources)
        try #require(baseline.isEmpty, "\(baseline.joined(separator: "\n"))")

        typealias Rule = (ReviewCardEvidenceSources) throws -> [String]
        let injections: [(file: ReviewCardEvidenceFile, declaration: String, line: String, rule: Rule)] = [
            (.todayReviewPage, "exactlyOne", "_ = query.firstMatch", ReviewCardEvidenceRules.forbiddenTokens(in:)),
            (.todayReviewPage, "exactlyOne", "Thread.sleep(forTimeInterval: 1)", ReviewCardEvidenceRules.forbiddenTokens(in:)),
            (.captureTests, "captureCanonicalStep", #"throw XCTSkip("flaky")"#, ReviewCardEvidenceRules.forbiddenTokens(in:)),
            (.captureTests, "captureCanonicalStep", "_ = try? startReview(app: app)", ReviewCardEvidenceRules.forbiddenTokens(in:)),
            (.captureTests, "captureCanonicalStep", #"attachText("ok", named: "card")"#, ReviewCardEvidenceRules.forbiddenTokens(in:)),
            (.settingsSheetPage, "navBar", "_ = app.buttons.element(boundBy: 0)", ReviewCardEvidenceRules.positionalPicks(in:)),
            (
                .captureTests,
                "captureCanonicalStep",
                #"captureStep("\(capture.assetID).\(capture.identity.cardID)", app: app)"#,
                ReviewCardEvidenceRules.captureFlow(in:)
            ),
            (.todayReviewPage, "frontAbsentFields", #"_ = ["explanatoin"]"#, ReviewCardEvidenceRules.fieldNames(in:)),
            // A loosened comparison added beside an intact check is still a violation.
            (.todayReviewPage, "waitForUnique", "_ = matches.count >= 1", ReviewCardEvidenceRules.cardinality(in:)),
            (.todayReviewPage, "cardMatchesGeometry", "_ = !matching.isEmpty", ReviewCardEvidenceRules.cardinality(in:)),
        ]
        for injection in injections {
            let mutated = try #require(
                sources.inserting(injection.line, atStartOf: injection.declaration, in: injection.file),
                "injection target \(injection.declaration) is missing from \(injection.file.rawValue)"
            )
            let violations = try injection.rule(mutated)
            #expect(!violations.isEmpty, "no rule fired for `\(injection.line)` in \(injection.declaration)")
        }

        // Remove each occurrence on its own: an accessor that checks in its polling
        // loop and again in its final return must fail when either copy goes.
        for check in ReviewCardEvidenceRules.cardinalityChecks {
            let weakenings = try sources.weakenings(check)
            #expect(
                weakenings.count == check.expected,
                "\(check.declaration) in \(check.file.rawValue): \(weakenings.count) sites of `\(check.pattern)`, expected \(check.expected)"
            )
            for (site, weakened) in weakenings.enumerated() {
                let noticed = ReviewCardEvidenceRules.violation(of: check, in: weakened) != nil
                #expect(noticed, "removing site \(site) of `\(check.pattern)` from \(check.declaration) went unnoticed")
            }
        }

        let unnamed = try #require(try sources.renamingFirstCaptureArgument(to: "capture"))
        let unnamedViolations = try ReviewCardEvidenceRules.captureFlow(in: unnamed)
        #expect(!unnamedViolations.isEmpty, "an unnamed capture path went unnoticed")
    }

    /// Realistic one-site weakenings: an accessor that keeps a second copy of its
    /// check (the polling loop and the final return) must still turn red when only
    /// one copy is loosened, and a loosened comparison is caught as such.
    @Test func partialCardinalityWeakeningTurnsTheContractRed() throws {
        let sources = try ReviewCardEvidenceSources.load()
        let weakenings: [(declaration: String, original: String, weakened: String)] = [
            ("waitForUnique", "if matches.count == 1, matches[0].exists", "if matches.count >= 1, matches[0].exists"),
            ("cardMatchesGeometry", "guard matching.count == 1 else", "guard !matching.isEmpty else"),
            ("waitForCardReadiness", "scopedCount(cardIdentifier, alternatePresentationIdentifier) == 0,", "true,"),
            ("scopedRequiredField", "return matching.count == 1 && matching[0].exists", "return !matching.isEmpty && matching[0].exists"),
            ("scopedPresentationAnchor", "return anchors.count == 1", "return anchors.count > 0"),
        ]
        for weakening in weakenings {
            let mutated = try #require(
                sources.replacingFirst(weakening.original, with: weakening.weakened, in: weakening.declaration, of: .todayReviewPage),
                "`\(weakening.original)` is missing from \(weakening.declaration)"
            )
            let violations = try ReviewCardEvidenceRules.cardinality(in: mutated)
            #expect(!violations.isEmpty, "weakening `\(weakening.original)` in \(weakening.declaration) went unnoticed")
        }
    }
}

// MARK: - Sources

/// The P12/P13 evidence path: the page objects the capture tests drive, and the
/// capture tests themselves.
private enum ReviewCardEvidenceFile: String, CaseIterable {
    case todayReviewPage = "BooksAndVocabUITests/Pages/TodayReviewPage.swift"
    case layoutEditorPage = "BooksAndVocabUITests/Pages/ReviewCardLayoutEditorPage.swift"
    case settingsSheetPage = "BooksAndVocabUITests/Pages/SettingsSheetPage.swift"
    case captureTests = "BooksAndVocabUITests/ReviewCardLayoutEditorUITests.swift"
}

private struct ReviewCardEvidenceSources {
    /// Comment-free source of each evidence file; every rule reads this.
    var codeByFile: [ReviewCardEvidenceFile: String]
    /// Raw values of the production `ReviewCardField`, the identifiers the
    /// renderer actually publishes.
    var productionFields: Set<String>

    static func load() throws -> Self {
        let iosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BooksAndVocabTests
            .deletingLastPathComponent() // ios
        var codeByFile: [ReviewCardEvidenceFile: String] = [:]
        for file in ReviewCardEvidenceFile.allCases {
            let source = try String(contentsOf: iosRoot.appendingPathComponent(file.rawValue), encoding: .utf8)
            codeByFile[file] = ReviewCardEvidenceRules.stripComments(source)
        }
        return Self(codeByFile: codeByFile, productionFields: Set(ReviewCardField.allCases.map(\.rawValue)))
    }

    func code(_ file: ReviewCardEvidenceFile) -> String {
        codeByFile[file] ?? ""
    }

    /// A copy with raw Swift `source` appended at the top level of `file`.
    func appending(_ source: String, to file: ReviewCardEvidenceFile) -> Self {
        var copy = self
        copy.codeByFile[file] = code(file) + ReviewCardEvidenceRules.stripComments(source)
        return copy
    }

    /// A copy whose `declaration` body starts with `line`.
    func inserting(_ line: String, atStartOf declaration: String, in file: ReviewCardEvidenceFile) -> Self? {
        var source = code(file)
        guard let body = ReviewCardEvidenceRules.bodyRange(of: declaration, in: source) else { return nil }
        source.insert(contentsOf: "\n\(line)\n", at: body.lowerBound)
        var copy = self
        copy.codeByFile[file] = source
        return copy
    }

    /// One copy per match of `check.pattern` inside its declaration, each with only
    /// that match replaced by `true`.
    func weakenings(_ check: ReviewCardEvidenceRules.CardinalityCheck) throws -> [Self] {
        let source = code(check.file)
        guard let body = ReviewCardEvidenceRules.bodyRange(of: check.declaration, in: source) else { return [] }
        return try ReviewCardEvidenceRules.matchRanges(check.pattern, in: source, within: body).map { site in
            var copy = self
            copy.codeByFile[check.file] = source.replacingCharacters(in: site, with: "true")
            return copy
        }
    }

    /// A copy with the first literal `original` inside `declaration` replaced.
    func replacingFirst(
        _ original: String,
        with replacement: String,
        in declaration: String,
        of file: ReviewCardEvidenceFile
    ) -> Self? {
        let source = code(file)
        guard let body = ReviewCardEvidenceRules.bodyRange(of: declaration, in: source),
              let site = source.range(of: original, range: body) else {
            return nil
        }
        var copy = self
        copy.codeByFile[file] = source.replacingCharacters(in: site, with: replacement)
        return copy
    }

    /// A copy whose first `captureCanonicalStep(<argument>, …)` call passes `name`.
    func renamingFirstCaptureArgument(to name: String) throws -> Self? {
        let source = code(.captureTests)
        let regex = try NSRegularExpression(pattern: ReviewCardEvidenceRules.captureCallPattern)
        guard let match = regex.firstMatch(in: source, range: NSRange(source.startIndex..., in: source)),
              let argument = Range(match.range(at: 1), in: source) else {
            return nil
        }
        var copy = self
        copy.codeByFile[.captureTests] = source.replacingCharacters(in: argument, with: name)
        return copy
    }
}

// MARK: - Rules

private enum ReviewCardEvidenceRules {
    /// `pattern` must match exactly `expected` times inside `declaration`: one per
    /// guard site, so loosening any single site (a polling loop and its final
    /// return each count) is a violation.
    typealias CardinalityCheck = (file: ReviewCardEvidenceFile, declaration: String, pattern: String, expected: Int)

    /// `firstMatch` silently picks one of several matches; any `sleep(` (`usleep`,
    /// `Thread.sleep`, `Task.sleep`) times readiness instead of observing it.
    static let forbiddenEverywhere = ["firstMatch", "sleep("]

    /// A capture test must fail rather than skip, swallow a readiness error, or
    /// attach text in place of a screenshot.
    static let forbiddenInCaptureTests = ["XCTSkip", "try?", "attachText"]

    /// The only declarations allowed to pick an element by position: query-only
    /// probes (absence and transition checks) whose callers wait first and assert
    /// cardinality separately.
    static let positionalPickOwners: [ReviewCardEvidenceFile: Set<String>] = [
        .todayReviewPage: ["queryElement", "scopedElement"],
    ]

    /// Evidence-critical accessors and the cardinality guards each must keep, one
    /// entry per guard with its exact number of sites.
    static let cardinalityChecks: [CardinalityCheck] = [
        (.todayReviewPage, "exactlyOne", #"XCTAssertEqual\(\s*matches\.count\s*,\s*1\s*,"#, 1),
        (.todayReviewPage, "element", #"exactlyOne\(identifier,"#, 1),
        (.todayReviewPage, "waitForUnique", #"matches\.count\s*==\s*1\b"#, 2),
        (.todayReviewPage, "cardIsCanonical", #"guard\s+matching\.count\s*==\s*1\s+else"#, 1),
        (.todayReviewPage, "cardMatchesGeometry", #"guard\s+matching\.count\s*==\s*1\s+else"#, 1),
        (.todayReviewPage, "cardMatchesGeometry", #"expandMatches\.count\s*==\s*geometry\.expectedExpandZoneCount\b"#, 1),
        (.todayReviewPage, "cardMatchesGeometry", #"guard\s+expandMatches\.count\s*==\s*1\s*,"#, 1),
        (.todayReviewPage, "scopedRequiredField", #"matching\.count\s*==\s*1\b"#, 1),
        (.todayReviewPage, "scopedElements", #"guard\s+cards\.count\s*==\s*1\s+else"#, 1),
        (.todayReviewPage, "scopedPresentationAnchor", #"anchors\.count\s*==\s*1\b"#, 1),
        // Readiness: every conjunct appears once in the polling loop and once in
        // the final return.
        (.todayReviewPage, "waitForCardReadiness", #"cardIsCanonical\(cardIdentifier,\s*identity:\s*identity\)"#, 2),
        (.todayReviewPage, "waitForCardReadiness", #"cardMatchesGeometry\(cardIdentifier,\s*geometry:\s*geometry\)"#, 2),
        (.todayReviewPage, "waitForCardReadiness", #"scopedPresentationAnchor\(cardIdentifier,\s*presentationIdentifier\)"#, 2),
        (
            .todayReviewPage, "waitForCardReadiness",
            #"scopedCount\(cardIdentifier,\s*alternatePresentationIdentifier\)\s*==\s*0\b"#, 2
        ),
        (
            .todayReviewPage, "waitForCardReadiness",
            #"requiredFieldIdentifiers\.allSatisfy\(\{\s*scopedRequiredField\(cardIdentifier,\s*\$0\)\s*\}\)"#, 2
        ),
        (
            .todayReviewPage, "waitForCardReadiness",
            #"absentFieldIdentifiers\.allSatisfy\(\{\s*scopedCount\(cardIdentifier,\s*\$0\)\s*==\s*0\s*\}\)"#, 2
        ),
        (.layoutEditorPage, "element", #"precondition\(\s*matching\.count\s*==\s*1\b"#, 1),
        (.layoutEditorPage, "presetSegment", #"precondition\(\s*buttons\.count\s*==\s*2\b"#, 1),
        (.layoutEditorPage, "waitUntilVisible", #"matches\.count\s*==\s*1\b"#, 2),
        (.settingsSheetPage, "navBar", #"precondition\(\s*matching\.count\s*==\s*1\b"#, 1),
        // `XCUIElementQuery.element` fails the test when the query is ambiguous.
        (.settingsSheetPage, "exact", #"\.matching\(identifier:\s*identifier\)\s*\.element\s*$"#, 1),
    ]

    /// Comparisons that accept more than one match. None belongs in a declaration
    /// `cardinalityChecks` guards, even beside an intact exact check.
    static let loosenedCardinalityPatterns = [
        #"\.count\s*(?:>=|>|!=|<=|<)"#,
        #"!\s*[A-Za-z_][\w.]*\.isEmpty\b"#,
    ]

    /// Computed lists in `TodayReviewPage.CardIdentity` that readiness turns into
    /// required and absent field identifiers.
    static let fieldListDeclarations = ["frontRequiredFields", "frontAbsentFields", "backRequiredFields", "backAbsentFields"]

    static let captureCallPattern = #"captureCanonicalStep\(\s*([\w.]+)\s*,"#

    static func all(in sources: ReviewCardEvidenceSources) throws -> [String] {
        try forbiddenTokens(in: sources) + positionalPicks(in: sources) + cardinality(in: sources)
            + captureFlow(in: sources) + fieldNames(in: sources)
    }

    static func forbiddenTokens(in sources: ReviewCardEvidenceSources) throws -> [String] {
        ReviewCardEvidenceFile.allCases.flatMap { file -> [String] in
            let code = sources.code(file)
            let tokens = forbiddenEverywhere + (file == .captureTests ? forbiddenInCaptureTests : [])
            return tokens.filter { code.contains($0) }.map { "\(file.rawValue) uses \($0)" }
        }
    }

    static func positionalPicks(in sources: ReviewCardEvidenceSources) throws -> [String] {
        let token = "element(boundBy:"
        return ReviewCardEvidenceFile.allCases.compactMap { file -> String? in
            let code = sources.code(file)
            let owners = positionalPickOwners[file, default: []].sorted()
            let allowed = owners.reduce(0) { count, owner in
                count + (bodyRange(of: owner, in: code).map { occurrences(of: token, in: String(code[$0])) } ?? 0)
            }
            guard occurrences(of: token, in: code) > allowed else { return nil }
            return "\(file.rawValue) uses \(token) outside the query-only helpers \(owners)"
        }
    }

    static func cardinality(in sources: ReviewCardEvidenceSources) throws -> [String] {
        var violations = cardinalityChecks.compactMap { violation(of: $0, in: sources) }
        var guarded: Set<String> = []
        for check in cardinalityChecks where guarded.insert("\(check.file.rawValue)#\(check.declaration)").inserted {
            let code = sources.code(check.file)
            guard let body = bodyRange(of: check.declaration, in: code) else { continue }
            for pattern in loosenedCardinalityPatterns
            where String(code[body]).range(of: pattern, options: .regularExpression) != nil {
                violations.append("\(check.file.rawValue): \(check.declaration) loosens a cardinality check (\(pattern))")
            }
        }
        return violations
    }

    static func violation(of check: CardinalityCheck, in sources: ReviewCardEvidenceSources) -> String? {
        let code = sources.code(check.file)
        guard let body = bodyRange(of: check.declaration, in: code) else {
            return "\(check.file.rawValue): \(check.declaration) is missing; a rename updates cardinalityChecks"
        }
        let sites = (try? matchRanges(check.pattern, in: code, within: body).count) ?? -1
        guard sites != check.expected else { return nil }
        return "\(check.file.rawValue): \(check.declaration) has \(sites) sites of \(check.pattern), expected \(check.expected)"
    }

    /// Every declared capture is taken by name through `captureCanonicalStep`, and
    /// that helper screenshots only after typed readiness, failing loudly otherwise.
    static func captureFlow(in sources: ReviewCardEvidenceSources) throws -> [String] {
        let code = sources.code(.captureTests)
        var violations: [String] = []

        if let helper = bodyRange(of: "captureCanonicalStep", in: code).map({ String(code[$0]) }) {
            let readiness = "waitForEvidenceReadiness(capture.readiness"
            let screenshot = #"captureStep("\(capture.assetID).\(capture.identity.cardID)""#
            if let wait = helper.range(of: readiness), let shot = helper.range(of: screenshot) {
                if shot.lowerBound < wait.lowerBound {
                    violations.append("captureCanonicalStep takes the screenshot before typed readiness")
                }
                let failure = helper[wait.upperBound...].range(of: #"else\s*\{[^}]*\}"#, options: .regularExpression)
                    .map { String(helper[$0]) } ?? ""
                if !(failure.contains(".not-ready.") && failure.contains("XCTFail(")) {
                    violations.append("captureCanonicalStep must capture diagnostics and XCTFail when readiness fails")
                }
            } else {
                violations.append("captureCanonicalStep must wait on capture.readiness, then capture the asset")
            }
        } else {
            violations.append("captureCanonicalStep is missing")
        }

        let declared = Set(try firstGroups(#"static\s+let\s+(\w+)\s*=\s*ReviewCardVisualEvidenceCapture\("#, in: code))
        if declared.isEmpty {
            violations.append("no ReviewCardVisualEvidenceCapture is declared")
        }
        var aliases: [String: String] = [:]
        for groups in try allGroups(#"let\s+(\w+)\s*=\s*ReviewCardVisualEvidenceStep\.(\w+)"#, in: code) where groups.count == 2 {
            aliases[groups[0]] = groups[1]
        }
        var taken: Set<String> = []
        let qualifier = "ReviewCardVisualEvidenceStep."
        for argument in try firstGroups(captureCallPattern, in: code) {
            let resolved = argument.hasPrefix(qualifier) ? String(argument.dropFirst(qualifier.count)) : aliases[argument]
            guard let resolved, declared.contains(resolved) else {
                violations.append("captureCanonicalStep(\(argument), …) does not name a declared capture")
                continue
            }
            taken.insert(resolved)
        }
        for name in declared.subtracting(taken).sorted() {
            violations.append("capture \(name) is declared but never taken through captureCanonicalStep")
        }
        return violations
    }

    static func fieldNames(in sources: ReviewCardEvidenceSources) throws -> [String] {
        var violations: [String] = []
        var named: [(String, String)] = []

        let page = sources.code(.todayReviewPage)
        for declaration in fieldListDeclarations {
            guard let body = bodyRange(of: declaration, in: page) else {
                violations.append("TodayReviewPage.\(declaration) is missing")
                continue
            }
            named += try firstGroups(#""(\w+)""#, in: String(page[body])).map { ("TodayReviewPage.\(declaration)", $0) }
        }
        let tests = sources.code(.captureTests)
        named += try firstGroups(#"backField\(\s*"(\w+)"\s*\)"#, in: tests).map { ("backField", $0) }
        for list in try firstGroups(#"for\s+field\s+in\s+\[([^\]]*)\]"#, in: tests) {
            named += try firstGroups(#""(\w+)""#, in: list).map { ("for field in", $0) }
        }

        if named.isEmpty {
            violations.append("no readiness field names found")
        }
        for (origin, field) in named where !sources.productionFields.contains(field) {
            violations.append("\(origin) names \"\(field)\", which is not a ReviewCardField")
        }
        return violations
    }

    // MARK: Source scanning

    /// `source` with comments removed and string literals kept, so documentation
    /// never trips a rule and a `//` inside a string never hides code. Scans UTF-8
    /// bytes: every delimiter is ASCII, and no multi-byte sequence contains one.
    static func stripComments(_ source: String) -> String {
        let slash = UInt8(ascii: "/"), star = UInt8(ascii: "*"), quote = UInt8(ascii: "\"")
        let backslash = UInt8(ascii: "\\"), newline = UInt8(ascii: "\n")
        let bytes = Array(source.utf8)
        var output: [UInt8] = []
        output.reserveCapacity(bytes.count)
        var index = 0
        var blockDepth = 0
        var inLineComment = false
        var openQuotes = 0 // 0 = code, 1 = "…", 3 = """…"""

        func byte(at offset: Int) -> UInt8? {
            index + offset < bytes.count ? bytes[index + offset] : nil
        }
        func atTripleQuote() -> Bool {
            byte(at: 0) == quote && byte(at: 1) == quote && byte(at: 2) == quote
        }

        while index < bytes.count {
            let current = bytes[index]
            if inLineComment {
                if current == newline {
                    inLineComment = false
                    output.append(current)
                }
                index += 1
            } else if blockDepth > 0 {
                if current == slash, byte(at: 1) == star {
                    blockDepth += 1
                    index += 2
                } else if current == star, byte(at: 1) == slash {
                    blockDepth -= 1
                    index += 2
                } else {
                    if current == newline { output.append(current) }
                    index += 1
                }
            } else if openQuotes > 0 {
                if current == backslash, index + 1 < bytes.count {
                    output += bytes[index...index + 1]
                    index += 2
                } else if current == quote, openQuotes == 1 || atTripleQuote() {
                    output += bytes[index..<index + openQuotes]
                    index += openQuotes
                    openQuotes = 0
                } else {
                    output.append(current)
                    index += 1
                }
            } else if current == slash, byte(at: 1) == slash {
                inLineComment = true
                index += 2
            } else if current == slash, byte(at: 1) == star {
                blockDepth = 1
                index += 2
            } else if current == quote {
                openQuotes = atTripleQuote() ? 3 : 1
                output += bytes[index..<index + openQuotes]
                index += openQuotes
            } else {
                output.append(current)
                index += 1
            }
        }
        return String(decoding: output, as: UTF8.self)
    }

    /// Range of the brace-delimited body of the first `func name` or `var name:`
    /// declaration in comment-free `code`.
    static func bodyRange(of name: String, in code: String) -> Range<String.Index>? {
        let declaration = #"(?:func\s+"# + name + #"\s*[(<]|va[rl]\s+"# + name + #"\s*:)"#
        let utf8 = code.utf8
        guard let match = code.range(of: declaration, options: .regularExpression),
              let open = utf8[match.upperBound...].firstIndex(of: UInt8(ascii: "{")) else {
            return nil
        }
        var depth = 0
        var index = open
        while index < utf8.endIndex {
            switch utf8[index] {
            case UInt8(ascii: "{"):
                depth += 1
            case UInt8(ascii: "}"):
                depth -= 1
                if depth == 0 { return utf8.index(after: open)..<index }
            default:
                break
            }
            index = utf8.index(after: index)
        }
        return nil
    }

    static func occurrences(of token: String, in text: String) -> Int {
        text.components(separatedBy: token).count - 1
    }

    /// Ranges of every match of `pattern` inside `scope` of `text`; the scope
    /// bounds act as text bounds for anchors.
    static func matchRanges(_ pattern: String, in text: String, within scope: Range<String.Index>) throws -> [Range<String.Index>] {
        let regex = try NSRegularExpression(pattern: pattern)
        return regex.matches(in: text, range: NSRange(scope, in: text)).compactMap { Range($0.range, in: text) }
    }

    /// The first capture group of every match of `pattern`.
    static func firstGroups(_ pattern: String, in text: String) throws -> [String] {
        try allGroups(pattern, in: text).compactMap(\.first)
    }

    /// Every capture group of every match of `pattern`.
    static func allGroups(_ pattern: String, in text: String) throws -> [[String]] {
        let regex = try NSRegularExpression(pattern: pattern)
        return regex.matches(in: text, range: NSRange(text.startIndex..., in: text)).map { match in
            (1..<match.numberOfRanges).compactMap { group in
                Range(match.range(at: group), in: text).map { String(text[$0]) }
            }
        }
    }
}
