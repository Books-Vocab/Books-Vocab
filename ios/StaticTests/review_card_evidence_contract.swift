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

try require(
    page.contains("func waitForFrontReadiness(") && page.contains("requiredFields: [String]")
        && page.contains("absentFields: [String]"),
    "front readiness must declare required and absent field contracts"
)
try require(
    page.contains("func waitForBackReadiness(") && page.contains("requiredFields: [String]")
        && page.contains("absentFields: [String]"),
    "back readiness must declare required and absent field contracts"
)
for requiredFragment in [
    "matching.count == 1",
    "frame.width > 0",
    "frame.height >= 100",
    "exactlyOne(presentationIdentifier)",
    "elements(for: alternatePresentationIdentifier).count == 0",
    "requiredFieldIdentifiers.allSatisfy({ exactlyOne($0) })",
    "absentFieldIdentifiers.allSatisfy({ elements(for: $0).count == 0 })",
] {
    try require(page.contains(requiredFragment), "readiness helper missing: \(requiredFragment)")
}

try requireOrder(
    evidence,
    "waitForFrontReadiness(\n            presentation: .natural,",
    "captureStep(ReviewCardVisualEvidenceStep.optionalSectionsCounterexample",
    "optional evidence capture must follow front readiness"
)
try require(
    evidence.contains("requiredFields: [\"partOfSpeech\"]")
        && evidence.contains("absentFields: [\"example\", \"explanation\", \"collocations\"]"),
    "optional evidence must name required and explicitly absent fields"
)

try requireOrder(
    evidence,
    "waitForFrontReadiness(\n            presentation: .scroll,",
    "captureStep(ReviewCardVisualEvidenceStep.largeTextCounterexample",
    "full front evidence capture must follow front readiness"
)
try requireOrder(
    evidence,
    "waitForBackReadiness(\n            presentation: .scroll,",
    "captureStep(ReviewCardVisualEvidenceStep.smallViewportCounterexample",
    "full back evidence capture must follow back readiness"
)
try require(
    evidence.contains("captureStep(ReviewCardVisualEvidenceStep.compactBackCounterexample"),
    "compact P12 path must have a named post-flip screenshot"
)
try requireOrder(
    evidence,
    "waitForBackReadiness(\n            presentation: .natural,",
    "captureStep(ReviewCardVisualEvidenceStep.compactBackCounterexample",
    "compact evidence capture must follow back readiness"
)
try require(
    evidence.contains("requiredFields: [\"difficultyTier\", \"graphLinks\"]")
        && evidence.contains("absentFields: [\"example\", \"explanation\", \"collocations\"]"),
    "compact evidence must name required and explicitly absent fields"
)
for failureStep in [
    "optional-sections-not-ready",
    "large-text-not-ready",
    "small-viewport-not-ready",
    "compact-back-not-ready",
] {
    try require(
        evidence.contains("captureStep(\"\(failureStep)\", app: app)")
            && evidence.contains("XCTFail("),
        "\(failureStep) must capture diagnostics and fail explicitly"
    )
    try requireAfter(
        evidence,
        "captureStep(\"\(failureStep)\", app: app)",
        "XCTFail(",
        "\(failureStep) must fail after its diagnostic capture"
    )
}
try require(!evidence.contains("XCTSkip") && !evidence.contains("try?"), "evidence path must not skip or swallow failures")
try require(!evidence.contains("Date().addingTimeInterval(0.8)"), "fixed sleep must not act as evidence readiness")
try require(
    reviewCard.contains("todayReview.card.front.field.\\(field.rawValue)"),
    "front optional fields need explicit accessibility identifiers"
)

print("review-card-evidence-contract: GREEN")
