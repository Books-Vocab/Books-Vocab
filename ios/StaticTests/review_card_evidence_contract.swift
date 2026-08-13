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
let editorPage = try read("ios/BooksAndVocabUITests/Pages/ReviewCardLayoutEditorPage.swift")
let settingsPage = try read("ios/BooksAndVocabUITests/Pages/SettingsSheetPage.swift")
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

func canonicalJSONData(_ value: Any) throws -> Data {
    guard JSONSerialization.isValidJSONObject(value) else {
        throw ContractFailure(message: "value is not JSON serializable")
    }
    return try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
}

func exactEntry(_ seed: [String: Any], cardID: String, _ message: String) throws -> [String: Any] {
    let entries = try jsonEntries(seed, message)
    let matches = entries.filter { $0["kgCardId"] as? String == cardID }
    try require(matches.count == 1, "\(message): \(cardID) must resolve once")
    guard let entry = matches.first else {
        throw ContractFailure(message: "\(message): missing \(cardID)")
    }
    return entry
}

let fixtureWorld = try jsonObject("ops/fixtures/ui_worlds/marketing_demo.json")
let generatedFixtureWorld = try jsonObject("ops/demo/generated/ios_fixture_dataset.json")
let reviewDeck = try jsonDictionary(fixtureWorld["reviewDeck"], "fixture must declare reviewDeck")
let generatedReviewDeck = try jsonDictionary(
    generatedFixtureWorld["reviewDeck"],
    "generated fixture must declare reviewDeck"
)
for fixtureID in ["review.card-full-info", "review.card-compact-counterexample"] {
    let repoSeed = try jsonDictionary(reviewDeck[fixtureID], "missing repo seed \(fixtureID)")
    let generatedSeed = try jsonDictionary(
        generatedReviewDeck[fixtureID],
        "missing generated seed \(fixtureID)"
    )
    let repoData = try canonicalJSONData(repoSeed)
    let generatedData = try canonicalJSONData(generatedSeed)
    try require(repoData == generatedData, "generated/source fixture drift for \(fixtureID)")
}

let fullInfoSeed = try jsonDictionary(
    reviewDeck["review.card-full-info"],
    "P13 canonical fixture review.card-full-info is missing"
)
let compactSeed = try jsonDictionary(
    reviewDeck["review.card-compact-counterexample"],
    "P12 canonical fixture review.card-compact-counterexample is missing"
)
let fullInfoEntries = try jsonEntries(fullInfoSeed, "P13 canonical fixture must contain entries")
let compactEntries = try jsonEntries(compactSeed, "P12 canonical fixture must contain entries")
let p13 = try exactEntry(fullInfoSeed, cardID: "review-card-full-coaxed", "P13 canonical fixture")
let p12 = try exactEntry(compactSeed, cardID: "review-card-compact-coaxed", "P12 canonical fixture")
try require(p13["word"] as? String == "coaxed", "P13 canonical card must pin frontWord coaxed")
try require(p13["reviewMode"] as? String == "production", "P13 canonical card must pin production mode")
try require(
    (p13["translation"] as? String)?.hasPrefix("說服；以溫和、耐心") == true,
    "P13 canonical card must pin the translation prefix"
)
try require(
    (p13["translation"] as? String)?.count ?? 0 >= 180,
    "P13 canonical card must retain a long translation"
)
try require(p12["word"] as? String == "coaxed", "P12 canonical card must pin frontWord coaxed")
try require(p12["reviewMode"] as? String == "recognition", "P12 canonical card must pin recognition mode")
try require(
    (p12["translation"] as? String)?.hasPrefix("說服、哄勸") == true,
    "P12 canonical card must pin the translation prefix"
)
try require(
    (p12["translation"] as? String)?.count ?? 0 >= 180,
    "P12 canonical card must retain a long translation"
)
try require(
    fullInfoEntries.filter { $0["reviewMode"] as? String == "recognition" }.count == 1,
    "P13 full-info fixture must keep the recognition counterexample distinct"
)
try require(
    compactEntries.filter { $0["reviewMode"] as? String == "recognition" }.count == 1,
    "P12 compact fixture must keep one recognition card"
)

try require(!page.contains("p12ProbeRecognitionCompact"), "P12 must not retain the probe identity")
try require(!evidence.contains("p12ProbeRecognitionCompact"), "evidence must not reference the probe identity")
try require(!page.contains("probe-001") && !evidence.contains("probe-001"), "probe payload shortcut is forbidden")
try require(!page.contains("minimumTranslationLength: 0"), "zero-length translation shortcut is forbidden")
for identity in [
    (name: "p12CompactCoaxedRecognition", cardID: "review-card-compact-coaxed", mode: "recognition", preset: "compact", prefix: "說服、哄勸", profile: "recognition:compact,production:compact"),
    (name: "p13Production", cardID: "review-card-full-coaxed", mode: "production", preset: "standard", prefix: "說服；以溫和、耐心", profile: "recognition:standard,production:standard"),
] {
    for fragment in [
        "static let \(identity.name) = CardIdentity(",
        "cardID: \"\(identity.cardID)\"",
        "frontWord: \"coaxed\"",
        "mode: .\(identity.mode)",
        "preset: .\(identity.preset)",
        "translationPrefix: \"\(identity.prefix)\"",
        "minimumTranslationLength: 180",
        "effectiveLayoutProfile: \"\(identity.profile)\"",
    ] {
        try require(page.contains(fragment), "canonical identity \(identity.name) missing \(fragment)")
    }
}

for requiredFragment in [
    "struct EvidenceReadinessContract",
    "enum CardFace",
    "struct CardGeometryContract",
    "func waitForEvidenceReadiness(",
    "switch contract.face",
    "case .front:",
    "case .back:",
    "func waitForFrontReadiness(",
    "func waitForBackReadiness(",
    "requiredFields: [String]",
    "absentFields: [String]",
    "cardMatchesGeometry",
    "geometry.minimumWidth",
    "geometry.minimumHeight",
    "geometry.expectedExpandZoneCount",
    "frame.minX.isFinite",
    "frame.maxY.isFinite",
    "bottomGap.isFinite",
    "matching.count == 1",
    "allElementsBoundByIndex",
    "identity.matches",
    "frontRequiredFields",
    "backRequiredFields",
    "exactlyOne(presentationIdentifier)",
    "elements(for: alternatePresentationIdentifier).count == 0",
    "requiredFieldIdentifiers.allSatisfy({ exactlyOne($0) })",
    "absentFieldIdentifiers.allSatisfy({ elements(for: $0).count == 0 })",
] {
    try require(page.contains(requiredFragment), "typed readiness missing: \(requiredFragment)")
}
for geometry in ["compactFront", "compactBack", "fullFront", "fullBack"] {
    try require(page.contains("static let \(geometry) = CardGeometryContract("), "missing geometry \(geometry)")
}
try require(
    page.contains("values[\"preset\"] == preset.rawValue")
        && page.contains("values[\"layoutProfile\"] == effectiveLayoutProfile"),
    "card identity must match live preset and effective layout profile"
)
try require(
    reviewCard.contains("let preset = profile.preset(for: card.reviewMode)")
        && reviewCard.contains("profile.recognition.rawValue")
        && reviewCard.contains("profile.production.rawValue")
        && reviewCard.contains("layoutProfile="),
    "production accessibility projection must publish the live layout profile"
)

let captureContracts: [(name: String, asset: String, fixture: String, identity: String, face: String, presentation: String, geometry: String)] = [
    ("optionalSectionsCounterexample", "optional-sections-counterexample", "notebookReviewCardCompactCounterexample", "p12CompactCoaxedRecognition", "front", "natural", "compactFront"),
    ("compactBackCounterexample", "compact-back-counterexample", "notebookReviewCardCompactCounterexample", "p12CompactCoaxedRecognition", "back", "natural", "compactBack"),
    ("largeTextCounterexample", "large-text-counterexample", "notebookReviewCardFullInfo", "p13Production", "front", "scroll", "fullFront"),
    ("smallViewportCounterexample", "small-viewport-counterexample", "notebookReviewCardFullInfo", "p13Production", "back", "scroll", "fullBack"),
]
for capture in captureContracts {
    for fragment in [
        "static let \(capture.name) = ReviewCardVisualEvidenceCapture(",
        "assetID: \"\(capture.asset)\"",
        "fixture: .\(capture.fixture)",
        "identity: .\(capture.identity)",
        "face: .\(capture.face)",
        "presentation: .\(capture.presentation)",
        "geometry: .\(capture.geometry)",
    ] {
        try require(evidence.contains(fragment), "capture \(capture.asset) missing \(fragment)")
    }
}
for namedPath in [
    "fixtures: [ReviewCardVisualEvidenceStep.optionalSectionsCounterexample.fixture]",
    "fixtures: [ReviewCardVisualEvidenceStep.compactBackCounterexample.fixture]",
    "fixtures: [ReviewCardVisualEvidenceStep.largeTextCounterexample.fixture]",
    "let optionalCapture = ReviewCardVisualEvidenceStep.optionalSectionsCounterexample",
    "let compactBackCapture = ReviewCardVisualEvidenceStep.compactBackCounterexample",
    "let frontCapture = ReviewCardVisualEvidenceStep.largeTextCounterexample",
    "let backCapture = ReviewCardVisualEvidenceStep.smallViewportCounterexample",
    "captureCanonicalStep(optionalCapture, review: review, app: app)",
    "captureCanonicalStep(compactBackCapture, review: review, app: app)",
    "captureCanonicalStep(frontCapture, review: review, app: app)",
    "captureCanonicalStep(backCapture, review: review, app: app)",
] {
    try require(evidence.contains(namedPath), "capture path is not named: \(namedPath)")
}
try require(
    evidence.contains("func captureCanonicalStep(")
        && evidence.contains("_ capture: ReviewCardVisualEvidenceCapture")
        && evidence.contains("waitForEvidenceReadiness(capture.readiness"),
    "capture helper must consume the typed readiness contract"
)
try requireOrder(
    evidence,
    "waitForEvidenceReadiness(capture.readiness",
    "captureStep(\"\\(capture.assetID).\\(capture.identity.cardID)",
    "screenshot must occur after complete typed readiness"
)
try require(
    evidence.contains("captureStep(\"\\(capture.assetID).not-ready.")
        && evidence.contains("XCTFail("),
    "readiness failure must capture diagnostics and fail explicitly"
)
try require(!evidence.contains("captureCanonicalStep(capture,"), "unnamed capture path is forbidden")
try require(!evidence.contains("hasCardIdentity"), "front-only identity helper is forbidden")
try require(!evidence.contains("XCTSkip"), "evidence path must not skip failures")
try require(!evidence.contains("attachText"), "evidence path must not attach synthetic text")
try require(!evidence.contains("sleep("), "evidence path must not use sleep as readiness")
try require(!evidence.contains("try?"), "evidence path must not swallow readiness failures")

let selectorSources: [(name: String, source: String)] = [
    ("TodayReviewPage", page),
    ("ReviewCardLayoutEditorPage", editorPage),
    ("SettingsSheetPage", settingsPage),
]
for selectorSource in selectorSources {
    try require(!selectorSource.source.contains("firstMatch"), "\(selectorSource.name) cannot use firstMatch")
    try require(!selectorSource.source.contains("element(boundBy:"), "\(selectorSource.name) cannot use unverified boundBy")
    try require(
        selectorSource.source.contains("allElementsBoundByIndex"),
        "\(selectorSource.name) must use cardinality-aware queries"
    )
}
try require(!evidence.contains("firstMatch"), "ReviewCardLayoutEditorUITests cannot use firstMatch")
try require(!evidence.contains("element(boundBy:"), "ReviewCardLayoutEditorUITests cannot use unverified boundBy")
try require(
    page.contains("precondition(\n            matching.count == 1")
        && editorPage.contains("precondition(\n            matching.count == 1")
        && settingsPage.contains("precondition(bars.count == 1"),
    "evidence-critical accessors must fail closed on cardinality drift"
)

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
