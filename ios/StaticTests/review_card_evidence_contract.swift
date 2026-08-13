import Foundation

struct ContractFailure: Error, CustomStringConvertible {
    let message: String

    var description: String { message }
}

let sourceRoot = URL(fileURLWithPath: #filePath)
    .deletingLastPathComponent() // StaticTests
    .deletingLastPathComponent() // ios
    .deletingLastPathComponent() // repo root

func read(_ relativePath: String) throws -> String {
    let url = sourceRoot.appendingPathComponent(relativePath)
    return try String(contentsOf: url, encoding: .utf8)
}

func require(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    guard condition() else { throw ContractFailure(message: message) }
}

func requireOrder(_ source: String, _ first: String, _ second: String, _ message: String) throws {
    guard let firstRange = source.range(of: first),
          let secondRange = source.range(of: second),
          firstRange.lowerBound < secondRange.lowerBound else {
        throw ContractFailure(message: message)
    }
}

func requireAfter(_ source: String, _ first: String, _ second: String, _ message: String) throws {
    guard let firstRange = source.range(of: first),
          source[firstRange.upperBound...].contains(second) else {
        throw ContractFailure(message: message)
    }
}

let page = try read("ios/BooksAndVocabUITests/Pages/TodayReviewPage.swift")
let evidence = try read("ios/BooksAndVocabUITests/ReviewCardLayoutEditorUITests.swift")
let reviewCard = try read("ios/BooksAndVocab/Views/Vocabulary/Scenes/ReviewCardView.swift")
let cardPresentation = try read("ios/BooksAndVocab/Views/Vocabulary/Presentation/CardPresentation.swift")
let launchHelper = try read("ios/BooksAndVocabUITests/Helpers/UITestAppLaunch.swift")
let layoutProfile = try read("ios/BooksAndVocab/Models/ReviewCardLayoutProfile.swift")

func jsonObject(_ relativePath: String) throws -> [String: Any] {
    let data = try Data(contentsOf: sourceRoot.appendingPathComponent(relativePath))
    guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
        throw ContractFailure(message: "fixture must decode as a JSON object: \(relativePath)")
    }
    return object
}

func jsonDictionary(_ value: Any?, _ message: String) throws -> [String: Any] {
    guard let dictionary = value as? [String: Any] else {
        throw ContractFailure(message: message)
    }
    return dictionary
}

func jsonEntries(_ seed: [String: Any], _ message: String) throws -> [[String: Any]] {
    guard let entries = seed["entries"] as? [[String: Any]], !entries.isEmpty else {
        throw ContractFailure(message: message)
    }
    return entries
}

let fixtureWorld = try jsonObject("ops/fixtures/ui_worlds/marketing_demo.json")
let reviewDeck = try jsonDictionary(fixtureWorld["reviewDeck"], "fixture must declare reviewDeck")
let fullInfoSeed = try jsonDictionary(
    reviewDeck["review.card-full-info"],
    "P13 canonical fixture review.card-full-info is missing"
)
let fullInfoEntries = try jsonEntries(fullInfoSeed, "P13 canonical fixture must contain entries")
let compactSeed = try jsonDictionary(
    reviewDeck["review.card-compact-counterexample"],
    "P12 canonical fixture review.card-compact-counterexample is missing"
)
let compactEntries = try jsonEntries(compactSeed, "P12 canonical fixture must contain entries")
let p13Entries = fullInfoEntries.filter { $0["kgCardId"] as? String == "review-card-full-coaxed" }
try require(p13Entries.count == 1, "P13 canonical card ID must resolve to exactly one fixture entry")
if let p13 = p13Entries.first {
    try require(p13["word"] as? String == "coaxed", "P13 canonical card must pin frontWord coaxed")
    try require(p13["reviewMode"] as? String == "production", "P13 canonical card must pin production mode")
    try require(
        (p13["translation"] as? String)?.count ?? 0 >= 180,
        "P13 canonical card must retain a long translation"
    )
}
let p13RecognitionEntries = fullInfoEntries.filter { $0["reviewMode"] as? String == "recognition" }
try require(
    p13RecognitionEntries.count == 1,
    "P13 full-info fixture must keep the recognition counterexample distinct from production"
)
let p12Entries = compactEntries.filter { $0["kgCardId"] as? String == "review-card-compact-coaxed" }
try require(p12Entries.count == 1, "P12 canonical compact card ID must resolve uniquely")
if let p12 = p12Entries.first {
    try require(p12["word"] as? String == "coaxed", "P12 canonical card must pin frontWord coaxed")
    try require(p12["reviewMode"] as? String == "recognition", "P12 canonical card must pin recognition mode")
}

try require(
    page.contains("func waitForFrontReadiness(") && page.contains("requiredFields: [String]")
        && page.contains("absentFields: [String]")
        && page.contains("CardIdentity")
        && page.contains("identity: CardIdentity"),
    "front readiness must declare identity-bound required and absent field contracts"
)
try require(
    page.contains("func waitForBackReadiness(") && page.contains("requiredFields: [String]")
        && page.contains("absentFields: [String]")
        && page.contains("identity: CardIdentity"),
    "back readiness must declare identity-bound required and absent field contracts"
)
for requiredFragment in [
    "matching.count == 1",
    "frame.width > 0",
    "frame.height >= 100",
    "exactlyOne(presentationIdentifier)",
    "elements(for: alternatePresentationIdentifier).count == 0",
    "requiredFieldIdentifiers.allSatisfy({ exactlyOne($0) })",
    "absentFieldIdentifiers.allSatisfy({ elements(for: $0).count == 0 })",
    "identity.matches",
    "frontRequiredFields",
    "backRequiredFields",
] {
    try require(page.contains(requiredFragment), "readiness helper missing: \(requiredFragment)")
}

try requireOrder(
    evidence,
    "waitForFrontReadiness(\n            identity: identity,\n            presentation: .natural,",
    "captureCanonicalStep(ReviewCardVisualEvidenceStep.optionalSectionsCounterexample",
    "optional evidence capture must follow front readiness"
)
try require(
    evidence.contains("CardIdentity.p12ProbeRecognitionCompact")
        && evidence.contains("CardIdentity.p13Production")
        && evidence.contains("captureCanonicalStep("),
    "P12/P13 evidence must bind readiness and screenshots to named canonical card identities"
)

try requireOrder(
    evidence,
    "waitForFrontReadiness(\n            identity: identity,\n            presentation: .scroll,",
    "captureCanonicalStep(ReviewCardVisualEvidenceStep.largeTextCounterexample",
    "full front evidence capture must follow front readiness"
)
try requireOrder(
    evidence,
    "waitForBackReadiness(\n            identity: identity,\n            presentation: .scroll,",
    "captureCanonicalStep(ReviewCardVisualEvidenceStep.smallViewportCounterexample",
    "full back evidence capture must follow back readiness"
)
try require(
    evidence.contains("captureCanonicalStep(ReviewCardVisualEvidenceStep.compactBackCounterexample"),
    "compact P12 path must have a named post-flip screenshot"
)
try requireOrder(
    evidence,
    "waitForBackReadiness(\n            identity: identity,\n            presentation: .natural,",
    "captureCanonicalStep(ReviewCardVisualEvidenceStep.compactBackCounterexample",
    "compact evidence capture must follow back readiness"
)
try require(
    evidence.contains("requiredFields: identity.backRequiredFields")
        && evidence.contains("absentFields: identity.backAbsentFields"),
    "compact evidence must derive required and absent back fields from the canonical identity"
)
for failureStep in [
    "optional-sections-not-ready",
    "large-text-not-ready",
    "small-viewport-not-ready",
    "compact-back-not-ready",
] {
    try require(
        evidence.contains("captureStep(\"\(failureStep).")
            && evidence.contains("XCTFail("),
        "\(failureStep) must capture diagnostics and fail explicitly"
    )
    try requireAfter(
        evidence,
        "captureStep(\"\(failureStep).",
        "XCTFail(",
        "\(failureStep) must fail after its diagnostic capture"
    )
}
try require(
    evidence.contains("CardIdentity.p13Production")
        && evidence.contains("frontRequiredFields")
        && evidence.contains("backRequiredFields"),
    "P13 readiness must derive fields from the canonical mode-aware identity"
)
try require(!evidence.contains("XCTSkip"), "evidence path must not skip failures")
try require(!evidence.contains("Date().addingTimeInterval(0.8)"), "fixed sleep must not act as evidence readiness")
try require(
    reviewCard.contains("todayReview.card.front.field.\\(field.rawValue)"),
    "front optional fields need explicit accessibility identifiers"
)
try require(
    reviewCard.contains("todayReview.card.back.field.\\(field.rawValue)"),
    "back optional fields need explicit accessibility identifiers"
)
for field in ["difficultyTier", "graphLinks", "example", "explanation", "collocations"] {
    try require(
        evidence.contains("\"\(field)\"") || page.contains("\"\(field)\""),
        "back field contract must name \(field)"
    )
}
try require(
    cardPresentation.contains("let kgCardId: String?")
        && cardPresentation.contains("kgCardId = entry.kgCardId"),
    "card presentation must carry fixture card identity into the rendered card"
)
try require(
    reviewCard.contains("accessibilityValue(evidenceIdentityValue(for: card))"),
    "rendered front/back cards must publish identity provenance"
)
try require(
    layoutProfile.contains("front: mode == .production ? [.partOfSpeech, .example]"),
    "production standard front contract must remain mode-aware and include example"
)
try require(
    launchHelper.contains("preconditionFailure(\"Invalid KG_UI_TEST_APP_ARGS_JSON")
        && !launchHelper.contains("let decoded = try? JSONDecoder().decode([String].self, from: data)"),
    "shared launch helper must fail closed on malformed inherited launch arguments"
)

print("review-card-evidence-contract: GREEN")
