import Foundation
import CryptoKit

private func uiWorldDataCorrupted(_ decoder: Decoder, _ description: String) -> DecodingError {
    .dataCorrupted(
        .init(codingPath: decoder.codingPath, debugDescription: description)
    )
}

private func uiWorldRequireExactKeys(
    _ rawContainer: KeyedDecodingContainer<AnyCodingKey>,
    expected: Set<String>,
    decoder: Decoder,
    label: String
) throws {
    let actual = Set(rawContainer.allKeys.map(\.stringValue))
    guard actual == expected else {
        let extra = actual.subtracting(expected).sorted()
        let missing = expected.subtracting(actual).sorted()
        throw uiWorldDataCorrupted(
            decoder,
            "\(label) keys must be exact; extra=\(extra), missing=\(missing)"
        )
    }
}

private func uiWorldRequireNonEmpty(
    _ value: String,
    decoder: Decoder,
    label: String
) throws -> String {
    guard !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
        throw uiWorldDataCorrupted(decoder, "\(label) must be non-empty")
    }
    return value
}

private func uiWorldRequireUnique(
    _ values: [String],
    decoder: Decoder,
    label: String,
    allowEmpty: Bool = true
) throws {
    if !allowEmpty && values.isEmpty {
        throw uiWorldDataCorrupted(decoder, "\(label) must be a non-empty list")
    }
    guard values.count == Set(values).count else {
        throw uiWorldDataCorrupted(decoder, "\(label) must be unique")
    }
}

private func uiWorldParseCanonicalDate(
    _ value: String,
    decoder: Decoder,
    label: String
) throws -> Date {
    let formatter = DateFormatter()
    formatter.locale = Locale(identifier: "en_US_POSIX")
    formatter.calendar = Calendar(identifier: .gregorian)
    formatter.timeZone = TimeZone(secondsFromGMT: 0)
    formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss'Z'"
    guard let date = formatter.date(from: value), formatter.string(from: date) == value else {
        throw uiWorldDataCorrupted(
            decoder,
            "\(label) must be YYYY-MM-DDTHH:MM:SSZ"
        )
    }
    return date
}

private func uiWorldParseAnchorDay(
    _ value: String,
    decoder: Decoder,
    label: String
) throws {
    let formatter = DateFormatter()
    formatter.locale = Locale(identifier: "en_US_POSIX")
    formatter.calendar = Calendar(identifier: .gregorian)
    formatter.timeZone = TimeZone(secondsFromGMT: 0)
    formatter.dateFormat = "yyyy-MM-dd"
    guard let date = formatter.date(from: value), formatter.string(from: date) == value else {
        throw uiWorldDataCorrupted(decoder, "\(label) must be YYYY-MM-DD")
    }
}

/// The shared review-clock contract has two exact wire shapes. Legacy worlds
/// retain the historical `frozenNow` object; canonical worlds use `now` and
/// `timeZone` and validate epoch/day consistency.
struct FixtureReviewClockSeed: Codable, Equatable {
    let now: String?
    let timeZone: String?
    let frozenNow: String?
    let frozenEpoch: Int?
    let anchorDay: String?
    let source: String?

    enum CodingKeys: String, CodingKey, CaseIterable {
        case now
        case timeZone
        case frozenNow
        case frozenEpoch
        case anchorDay
        case source
    }

    private static let legacyKeys: Set<String> = ["frozenNow", "frozenEpoch", "anchorDay", "source"]
    private static let canonicalKeys: Set<String> = ["now", "timeZone", "frozenEpoch", "anchorDay", "source"]

    var isCanonical: Bool {
        now != nil && timeZone != nil && frozenEpoch != nil && anchorDay != nil && source != nil
    }

    init(
        now: String? = nil,
        timeZone: String? = nil,
        frozenNow: String? = nil,
        frozenEpoch: Int? = nil,
        anchorDay: String? = nil,
        source: String? = nil
    ) {
        self.now = now
        self.timeZone = timeZone
        self.frozenNow = frozenNow
        self.frozenEpoch = frozenEpoch
        self.anchorDay = anchorDay
        self.source = source
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let keys = Set(rawContainer.allKeys.map(\.stringValue))
        let container = try decoder.container(keyedBy: CodingKeys.self)
        if keys == Self.legacyKeys {
            now = nil
            timeZone = nil
            frozenNow = try container.decode(String.self, forKey: .frozenNow)
            frozenEpoch = try container.decode(Int.self, forKey: .frozenEpoch)
            anchorDay = try container.decode(String.self, forKey: .anchorDay)
            source = try container.decode(String.self, forKey: .source)
            _ = try uiWorldRequireNonEmpty(
                frozenNow!, decoder: decoder, label: "scenarioContext.reviewClock.frozenNow"
            )
            try uiWorldParseCanonicalDate(
                frozenNow!, decoder: decoder, label: "scenarioContext.reviewClock.frozenNow"
            )
            try uiWorldParseAnchorDay(
                anchorDay!, decoder: decoder, label: "scenarioContext.reviewClock.anchorDay"
            )
            _ = try uiWorldRequireNonEmpty(
                source!, decoder: decoder, label: "scenarioContext.reviewClock.source"
            )
        } else if keys == Self.canonicalKeys {
            now = try container.decode(String.self, forKey: .now)
            timeZone = try container.decode(String.self, forKey: .timeZone)
            frozenNow = nil
            frozenEpoch = try container.decode(Int.self, forKey: .frozenEpoch)
            anchorDay = try container.decode(String.self, forKey: .anchorDay)
            source = try container.decode(String.self, forKey: .source)
            let date = try uiWorldParseCanonicalDate(
                now!, decoder: decoder, label: "scenarioContext.reviewClock.now"
            )
            guard let zone = TimeZone(identifier: timeZone!),
                  !timeZone!.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                throw uiWorldDataCorrupted(
                    decoder,
                    "scenarioContext.reviewClock.timeZone must be a valid identifier"
                )
            }
            guard frozenEpoch == Int(date.timeIntervalSince1970) else {
                throw uiWorldDataCorrupted(
                    decoder,
                    "scenarioContext.reviewClock.frozenEpoch must match now"
                )
            }
            try uiWorldParseAnchorDay(
                anchorDay!, decoder: decoder, label: "scenarioContext.reviewClock.anchorDay"
            )
            let dayFormatter = DateFormatter()
            dayFormatter.locale = Locale(identifier: "en_US_POSIX")
            dayFormatter.calendar = Calendar(identifier: .gregorian)
            dayFormatter.timeZone = zone
            dayFormatter.dateFormat = "yyyy-MM-dd"
            guard dayFormatter.string(from: date) == anchorDay else {
                throw uiWorldDataCorrupted(
                    decoder,
                    "scenarioContext.reviewClock.anchorDay must match now/timeZone"
                )
            }
            _ = try uiWorldRequireNonEmpty(
                source!, decoder: decoder, label: "scenarioContext.reviewClock.source"
            )
        } else {
            try uiWorldRequireExactKeys(
                rawContainer,
                expected: Self.canonicalKeys,
                decoder: decoder,
                label: "scenarioContext.reviewClock"
            )
            now = nil
            timeZone = nil
            frozenNow = nil
            frozenEpoch = nil
            anchorDay = nil
            source = nil
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        if isCanonical {
            try container.encode(now, forKey: .now)
            try container.encode(timeZone, forKey: .timeZone)
            try container.encode(frozenEpoch, forKey: .frozenEpoch)
            try container.encode(anchorDay, forKey: .anchorDay)
            try container.encode(source, forKey: .source)
        } else {
            try container.encode(frozenNow, forKey: .frozenNow)
            try container.encode(frozenEpoch, forKey: .frozenEpoch)
            try container.encode(anchorDay, forKey: .anchorDay)
            try container.encode(source, forKey: .source)
        }
    }
}

enum UIWorldDictionaryFixtureID: String, CaseIterable {
    case p1DictionaryRich = "ui-p1-dictionary-rich"
    case p2DictionarySenses = "ui-p2-dictionary-senses"

    var requiredStepLabel: String {
        switch self {
        case .p1DictionaryRich:
            return "dictionary-rich"
        case .p2DictionarySenses:
            return "dictionary-senses"
        }
    }
}

enum UIWorldDictionaryCounterexampleID: String, CaseIterable {
    case p2MissingExample = "dictionary.p2.missing-example"
    case p2MaterializeError = "dictionary.p2.materialize-error"

    var stepLabel: String {
        switch self {
        case .p2MissingExample:
            return "missing-example-counterexample"
        case .p2MaterializeError:
            return "materialize-error-counterexample"
        }
    }
}

enum UIWorldDictionaryLookupState: String, CaseIterable {
    case idle
    case loading
    case result
    case partial
    case offline
    case error
    case retry

    var fixtureID: String { "dictionary.lookup.\(rawValue)" }
}

struct UIWorldDictionaryLookupSeed: Codable, Equatable {
    let fixtureID: String
    let stepLabel: String

    enum CodingKeys: String, CodingKey, CaseIterable {
        case fixtureID
        case stepLabel
    }

    init(from decoder: Decoder) throws {
        let raw = try decoder.container(keyedBy: AnyCodingKey.self)
        try uiWorldRequireExactKeys(raw, expected: ["fixtureID", "stepLabel"], decoder: decoder, label: "dictionary.lookup")
        let container = try decoder.container(keyedBy: CodingKeys.self)
        fixtureID = try uiWorldRequireNonEmpty(
            container.decode(String.self, forKey: .fixtureID),
            decoder: decoder,
            label: "dictionary.lookup.fixtureID"
        )
        stepLabel = try uiWorldRequireNonEmpty(
            container.decode(String.self, forKey: .stepLabel),
            decoder: decoder,
            label: "dictionary.lookup.stepLabel"
        )
    }
}

struct UIWorldDictionarySenseSeed: Codable, Equatable {
    let id: String
    let partOfSpeech: String
    let gloss: String
    let exampleIDs: [String]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case id
        case partOfSpeech
        case gloss
        case exampleIDs
    }

    init(from decoder: Decoder) throws {
        let raw = try decoder.container(keyedBy: AnyCodingKey.self)
        try uiWorldRequireExactKeys(raw, expected: ["id", "partOfSpeech", "gloss", "exampleIDs"], decoder: decoder, label: "dictionary.sense")
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try uiWorldRequireNonEmpty(container.decode(String.self, forKey: .id), decoder: decoder, label: "dictionary.sense.id")
        partOfSpeech = try uiWorldRequireNonEmpty(container.decode(String.self, forKey: .partOfSpeech), decoder: decoder, label: "dictionary.sense.partOfSpeech")
        gloss = try uiWorldRequireNonEmpty(container.decode(String.self, forKey: .gloss), decoder: decoder, label: "dictionary.sense.gloss")
        exampleIDs = try container.decode([String].self, forKey: .exampleIDs)
        try uiWorldRequireUnique(exampleIDs, decoder: decoder, label: "dictionary.sense.exampleIDs", allowEmpty: false)
        for value in exampleIDs {
            _ = try uiWorldRequireNonEmpty(value, decoder: decoder, label: "dictionary.sense.exampleIDs")
        }
    }
}

struct UIWorldDictionaryExampleSeed: Codable, Equatable {
    let id: String
    let senseID: String
    let text: String

    enum CodingKeys: String, CodingKey, CaseIterable {
        case id
        case senseID
        case text
    }

    init(from decoder: Decoder) throws {
        let raw = try decoder.container(keyedBy: AnyCodingKey.self)
        try uiWorldRequireExactKeys(raw, expected: ["id", "senseID", "text"], decoder: decoder, label: "dictionary.example")
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try uiWorldRequireNonEmpty(container.decode(String.self, forKey: .id), decoder: decoder, label: "dictionary.example.id")
        senseID = try uiWorldRequireNonEmpty(container.decode(String.self, forKey: .senseID), decoder: decoder, label: "dictionary.example.senseID")
        text = try uiWorldRequireNonEmpty(container.decode(String.self, forKey: .text), decoder: decoder, label: "dictionary.example.text")
    }
}

struct UIWorldDictionaryProvenanceSeed: Codable, Equatable {
    let provider: String
    let entryID: String
    let sourceLabel: String

    enum CodingKeys: String, CodingKey, CaseIterable {
        case provider
        case entryID
        case sourceLabel
    }

    init(from decoder: Decoder) throws {
        let raw = try decoder.container(keyedBy: AnyCodingKey.self)
        try uiWorldRequireExactKeys(raw, expected: ["provider", "entryID", "sourceLabel"], decoder: decoder, label: "dictionary.provenance")
        let container = try decoder.container(keyedBy: CodingKeys.self)
        provider = try uiWorldRequireNonEmpty(container.decode(String.self, forKey: .provider), decoder: decoder, label: "dictionary.provenance.provider")
        entryID = try uiWorldRequireNonEmpty(container.decode(String.self, forKey: .entryID), decoder: decoder, label: "dictionary.provenance.entryID")
        sourceLabel = try uiWorldRequireNonEmpty(container.decode(String.self, forKey: .sourceLabel), decoder: decoder, label: "dictionary.provenance.sourceLabel")
    }
}

struct UIWorldDictionaryMaterializationSeed: Codable, Equatable {
    let status: String
    let selectedSenseID: String?
    let selectedExampleID: String?
    let sourceFixtureID: String

    enum CodingKeys: String, CodingKey, CaseIterable {
        case status
        case selectedSenseID
        case selectedExampleID
        case sourceFixtureID
    }

    init(from decoder: Decoder) throws {
        let raw = try decoder.container(keyedBy: AnyCodingKey.self)
        try uiWorldRequireExactKeys(raw, expected: ["status", "selectedSenseID", "selectedExampleID", "sourceFixtureID"], decoder: decoder, label: "dictionary.materialization")
        let container = try decoder.container(keyedBy: CodingKeys.self)
        status = try uiWorldRequireNonEmpty(container.decode(String.self, forKey: .status), decoder: decoder, label: "dictionary.materialization.status")
        guard ["pending", "ready", "failed"].contains(status) else {
            throw uiWorldDataCorrupted(decoder, "dictionary.materialization.status is invalid")
        }
        selectedSenseID = try container.decodeIfPresent(String.self, forKey: .selectedSenseID)
        selectedExampleID = try container.decodeIfPresent(String.self, forKey: .selectedExampleID)
        sourceFixtureID = try uiWorldRequireNonEmpty(container.decode(String.self, forKey: .sourceFixtureID), decoder: decoder, label: "dictionary.materialization.sourceFixtureID")
        if status == "ready" {
            guard selectedSenseID != nil, selectedExampleID != nil else {
                throw uiWorldDataCorrupted(decoder, "dictionary.materialization ready requires selected sense/example")
            }
        } else if selectedSenseID != nil || selectedExampleID != nil {
            throw uiWorldDataCorrupted(decoder, "dictionary.materialization pending/failed must not carry selected sense/example")
        }
    }
}

struct UIWorldAssetCoverageSeed: Codable, Equatable {
    let fixtureIDs: [String]
    let stepLabels: [String]
    let assetIDs: [String]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case fixtureIDs
        case stepLabels
        case assetIDs
    }

    init(from decoder: Decoder) throws {
        let raw = try decoder.container(keyedBy: AnyCodingKey.self)
        try uiWorldRequireExactKeys(raw, expected: ["fixtureIDs", "stepLabels", "assetIDs"], decoder: decoder, label: "asset coverage")
        let container = try decoder.container(keyedBy: CodingKeys.self)
        fixtureIDs = try container.decode([String].self, forKey: .fixtureIDs)
        stepLabels = try container.decode([String].self, forKey: .stepLabels)
        assetIDs = try container.decode([String].self, forKey: .assetIDs)
        try uiWorldRequireUnique(fixtureIDs, decoder: decoder, label: "asset coverage.fixtureIDs")
        try uiWorldRequireUnique(stepLabels, decoder: decoder, label: "asset coverage.stepLabels")
        try uiWorldRequireUnique(assetIDs, decoder: decoder, label: "asset coverage.assetIDs")
        for value in fixtureIDs + stepLabels + assetIDs {
            _ = try uiWorldRequireNonEmpty(value, decoder: decoder, label: "asset coverage value")
        }
    }
}

struct UIWorldDictionarySeed: Codable, Equatable {
    let lookup: [String: UIWorldDictionaryLookupSeed]
    let senses: [UIWorldDictionarySenseSeed]
    let examples: [UIWorldDictionaryExampleSeed]
    let provenance: UIWorldDictionaryProvenanceSeed
    let materialization: UIWorldDictionaryMaterializationSeed
    let coverage: [String: UIWorldAssetCoverageSeed]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case lookup
        case senses
        case examples
        case provenance
        case materialization
        case coverage
    }

    private static let lookupStates = Set(UIWorldDictionaryLookupState.allCases.map(\.rawValue))

    init(from decoder: Decoder) throws {
        let raw = try decoder.container(keyedBy: AnyCodingKey.self)
        try uiWorldRequireExactKeys(raw, expected: ["lookup", "senses", "examples", "provenance", "materialization", "coverage"], decoder: decoder, label: "scenarioContext.dictionary")
        let container = try decoder.container(keyedBy: CodingKeys.self)
        lookup = try container.decode([String: UIWorldDictionaryLookupSeed].self, forKey: .lookup)
        senses = try container.decode([UIWorldDictionarySenseSeed].self, forKey: .senses)
        examples = try container.decode([UIWorldDictionaryExampleSeed].self, forKey: .examples)
        provenance = try container.decode(UIWorldDictionaryProvenanceSeed.self, forKey: .provenance)
        materialization = try container.decode(UIWorldDictionaryMaterializationSeed.self, forKey: .materialization)
        coverage = try container.decode([String: UIWorldAssetCoverageSeed].self, forKey: .coverage)
        try validateShape(decoder: decoder)
    }

    private func validateShape(decoder: Decoder) throws {
        guard Set(lookup.keys) == Self.lookupStates else {
            throw uiWorldDataCorrupted(decoder, "dictionary.lookup states must be exact")
        }
        guard !senses.isEmpty, !examples.isEmpty else {
            throw uiWorldDataCorrupted(decoder, "dictionary senses/examples must be non-empty")
        }
        guard Set(senses.map(\.id)).count == senses.count else {
            throw uiWorldDataCorrupted(decoder, "dictionary.senses.id must be unique")
        }
        guard Set(examples.map(\.id)).count == examples.count else {
            throw uiWorldDataCorrupted(decoder, "dictionary.examples.id must be unique")
        }
        guard Set(lookup.values.map(\.fixtureID)).count == lookup.count else {
            throw uiWorldDataCorrupted(decoder, "dictionary.lookup.fixtureID must be unique")
        }
        guard Set(lookup.values.map(\.stepLabel)).count == lookup.count else {
            throw uiWorldDataCorrupted(decoder, "dictionary.lookup.stepLabel must be unique")
        }
        let senseIDs = Set(senses.map(\.id))
        let exampleByID = Dictionary(uniqueKeysWithValues: examples.map { ($0.id, $0) })
        var referencedExampleIDs: Set<String> = []
        for sense in senses {
            for exampleID in sense.exampleIDs {
                guard let example = exampleByID[exampleID], example.senseID == sense.id else {
                    throw uiWorldDataCorrupted(decoder, "dictionary sense/example references must correspond")
                }
                referencedExampleIDs.insert(exampleID)
            }
        }
        guard referencedExampleIDs == Set(exampleByID.keys) else {
            throw uiWorldDataCorrupted(decoder, "dictionary examples must be referenced by their sense")
        }
        guard examples.allSatisfy({ senseIDs.contains($0.senseID) }) else {
            throw uiWorldDataCorrupted(decoder, "dictionary.example.senseID references unknown sense")
        }
        guard lookup.values.contains(where: { $0.fixtureID == materialization.sourceFixtureID }) else {
            throw uiWorldDataCorrupted(decoder, "dictionary.materialization.sourceFixtureID must reference lookup")
        }
        if materialization.status == "ready" {
            guard let selectedSenseID = materialization.selectedSenseID,
                  let selectedExampleID = materialization.selectedExampleID,
                  senseIDs.contains(selectedSenseID),
                  let example = exampleByID[selectedExampleID],
                  example.senseID == selectedSenseID else {
                throw uiWorldDataCorrupted(decoder, "dictionary materialization selected sense/example must correspond")
            }
        }
        guard Set(coverage.keys) == Set(["required", "counterexamples"]) else {
            throw uiWorldDataCorrupted(decoder, "dictionary.coverage keys must be required/counterexamples")
        }
        guard let required = coverage["required"], !required.fixtureIDs.isEmpty, !required.stepLabels.isEmpty,
              let counterexamples = coverage["counterexamples"] else {
            throw uiWorldDataCorrupted(decoder, "dictionary.coverage required must be non-empty")
        }
        try validateDisjoint(required, counterexamples, decoder: decoder, label: "dictionary.coverage")
    }

    private func validateDisjoint(
        _ required: UIWorldAssetCoverageSeed,
        _ counterexamples: UIWorldAssetCoverageSeed,
        decoder: Decoder,
        label: String
    ) throws {
        let pairs: [(String, Set<String>, Set<String>)] = [
            ("fixtureIDs", Set(required.fixtureIDs), Set(counterexamples.fixtureIDs)),
            ("stepLabels", Set(required.stepLabels), Set(counterexamples.stepLabels)),
            ("assetIDs", Set(required.assetIDs), Set(counterexamples.assetIDs)),
        ]
        for (name, requiredValues, counterexampleValues) in pairs where !requiredValues.isDisjoint(with: counterexampleValues) {
            throw uiWorldDataCorrupted(decoder, "\(label).\(name) required/counterexamples must be disjoint")
        }
    }

    func validate(assets: UIWorldAssetManifest, decoder: Decoder) throws {
        let assetTypes = assets.typeByID
        for (name, values) in coverage {
            guard Set(values.assetIDs).isSubset(of: Set(assetTypes.keys)) else {
                throw uiWorldDataCorrupted(decoder, "dictionary.coverage.\(name).assetIDs must resolve to manifest assets")
            }
        }
    }
}

struct UIWorldSurfaceContractRowSeed: Codable, Equatable {
    let fixtureID: String
    let stepLabel: String
    let index: Int
    let assetIDs: [String]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case fixtureID
        case stepLabel
        case index
        case assetIDs
    }

    init(fixtureID: String, stepLabel: String, index: Int, assetIDs: [String]) {
        self.fixtureID = fixtureID
        self.stepLabel = stepLabel
        self.index = index
        self.assetIDs = assetIDs
    }

    init(from decoder: Decoder) throws {
        let raw = try decoder.container(keyedBy: AnyCodingKey.self)
        try uiWorldRequireExactKeys(raw, expected: ["fixtureID", "stepLabel", "index", "assetIDs"], decoder: decoder, label: "surface contract row")
        let container = try decoder.container(keyedBy: CodingKeys.self)
        fixtureID = try uiWorldRequireNonEmpty(container.decode(String.self, forKey: .fixtureID), decoder: decoder, label: "surface contract.fixtureID")
        stepLabel = try uiWorldRequireNonEmpty(container.decode(String.self, forKey: .stepLabel), decoder: decoder, label: "surface contract.stepLabel")
        index = try container.decode(Int.self, forKey: .index)
        guard index >= 0 else {
            throw uiWorldDataCorrupted(decoder, "surface contract.index must be non-negative")
        }
        assetIDs = try container.decode([String].self, forKey: .assetIDs)
        try uiWorldRequireUnique(assetIDs, decoder: decoder, label: "surface contract.assetIDs")
        for value in assetIDs {
            _ = try uiWorldRequireNonEmpty(value, decoder: decoder, label: "surface contract.assetIDs value")
        }
    }
}

struct UIWorldSurfaceContractSeed: Codable, Equatable {
    let required: [UIWorldSurfaceContractRowSeed]
    let counterexamples: [UIWorldSurfaceContractRowSeed]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case required
        case counterexamples
    }

    init(
        required: [UIWorldSurfaceContractRowSeed],
        counterexamples: [UIWorldSurfaceContractRowSeed]
    ) {
        self.required = required
        self.counterexamples = counterexamples
    }

    init(from decoder: Decoder) throws {
        let raw = try decoder.container(keyedBy: AnyCodingKey.self)
        try uiWorldRequireExactKeys(raw, expected: ["required", "counterexamples"], decoder: decoder, label: "surface contract")
        let container = try decoder.container(keyedBy: CodingKeys.self)
        required = try container.decode([UIWorldSurfaceContractRowSeed].self, forKey: .required)
        counterexamples = try container.decode([UIWorldSurfaceContractRowSeed].self, forKey: .counterexamples)
        guard !required.isEmpty else {
            throw uiWorldDataCorrupted(decoder, "surface contract.required must be non-empty")
        }
        try validateUnique(required, decoder: decoder, label: "surface contract.required")
        try validateUnique(counterexamples, decoder: decoder, label: "surface contract.counterexamples")
        let pairs: [(String, Set<String>, Set<String>)] = [
            ("fixtureID", Set(required.map(\.fixtureID)), Set(counterexamples.map(\.fixtureID))),
            ("stepLabel", Set(required.map(\.stepLabel)), Set(counterexamples.map(\.stepLabel))),
            ("index", Set(required.map { String($0.index) }), Set(counterexamples.map { String($0.index) })),
            ("assetIDs", Set(required.flatMap(\.assetIDs)), Set(counterexamples.flatMap(\.assetIDs))),
        ]
        for (name, requiredValues, counterexampleValues) in pairs where !requiredValues.isDisjoint(with: counterexampleValues) {
            throw uiWorldDataCorrupted(decoder, "surface contract.\(name) required/counterexamples must be disjoint")
        }
    }

    private func validateUnique(
        _ rows: [UIWorldSurfaceContractRowSeed],
        decoder: Decoder,
        label: String
    ) throws {
        guard Set(rows.map(\.fixtureID)).count == rows.count,
              Set(rows.map(\.stepLabel)).count == rows.count,
              Set(rows.map { $0.index }).count == rows.count else {
            throw uiWorldDataCorrupted(decoder, "\(label) fixtureID/stepLabel/index must be unique")
        }
    }

    func validate(assets: UIWorldAssetManifest, decoder: Decoder) throws {
        let assetTypes = assets.typeByID
        for row in required + counterexamples {
            guard Set(row.assetIDs).isSubset(of: Set(assetTypes.keys)) else {
                throw uiWorldDataCorrupted(decoder, "surface contract assetIDs must resolve to manifest assets")
            }
        }
    }
}

struct UIWorldScenarioContextSeed: Codable, Equatable {
    /// Legacy worlds use exactly these three keys; canonical worlds add the
    /// dictionary and surface contracts as an inseparable five-key shape.
    let reviewClock: FixtureReviewClockSeed?
    let dictionary: UIWorldDictionarySeed?
    let surfaceContracts: [String: UIWorldSurfaceContractSeed]?
    let readerPassage: UIWorldReaderPassageSeed?
    let wordDetail: UIWorldVocabularySeed?

    enum CodingKeys: String, CodingKey, CaseIterable {
        case reviewClock
        case dictionary
        case readerPassage
        case wordDetail
        case surfaceContracts
    }

    private static let legacyKeys: Set<String> = ["reviewClock", "readerPassage", "wordDetail"]
    private static let canonicalKeys: Set<String> = ["reviewClock", "dictionary", "surfaceContracts", "readerPassage", "wordDetail"]

    init(
        reviewClock: FixtureReviewClockSeed? = nil,
        dictionary: UIWorldDictionarySeed? = nil,
        surfaceContracts: [String: UIWorldSurfaceContractSeed]? = nil,
        readerPassage: UIWorldReaderPassageSeed? = nil,
        wordDetail: UIWorldVocabularySeed? = nil
    ) {
        self.reviewClock = reviewClock
        self.dictionary = dictionary
        self.readerPassage = readerPassage
        self.wordDetail = wordDetail
        self.surfaceContracts = surfaceContracts
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let keys = Set(rawContainer.allKeys.map(\.stringValue))
        guard keys == Self.legacyKeys || keys == Self.canonicalKeys else {
            try uiWorldRequireExactKeys(rawContainer, expected: Self.canonicalKeys, decoder: decoder, label: "UI World scenarioContext")
            throw uiWorldDataCorrupted(decoder, "UI World scenarioContext has an unsupported key shape")
        }
        let container = try decoder.container(keyedBy: CodingKeys.self)
        reviewClock = try container.decodeIfPresent(FixtureReviewClockSeed.self, forKey: .reviewClock)
        readerPassage = try container.decodeIfPresent(UIWorldReaderPassageSeed.self, forKey: .readerPassage)
        wordDetail = try container.decodeIfPresent(UIWorldVocabularySeed.self, forKey: .wordDetail)
        if keys == Self.canonicalKeys {
            guard reviewClock?.isCanonical == true else {
                throw uiWorldDataCorrupted(decoder, "canonical scenarioContext requires canonical reviewClock")
            }
            dictionary = try container.decode(UIWorldDictionarySeed.self, forKey: .dictionary)
            surfaceContracts = try container.decode([String: UIWorldSurfaceContractSeed].self, forKey: .surfaceContracts)
            guard surfaceContracts?.keys.contains("explore") == true,
                  surfaceContracts?.keys.contains("settings") == true else {
                throw uiWorldDataCorrupted(decoder, "canonical scenarioContext requires explore/settings surfaceContracts")
            }
        } else {
            guard reviewClock?.isCanonical != true else {
                throw uiWorldDataCorrupted(decoder, "legacy scenarioContext cannot use canonical reviewClock")
            }
            dictionary = nil
            surfaceContracts = nil
        }
    }

    func validate(
        assets: UIWorldAssetManifest,
        vocabulary: [String: UIWorldVocabularySeed],
        sharedDecks: UIWorldSharedDeckCatalogSeed,
        decoder: Decoder
    ) throws {
        guard readerPassage != nil, wordDetail != nil else {
            throw uiWorldDataCorrupted(decoder, "scenarioContext must declare readerPassage and wordDetail")
        }
        guard let dictionary, let surfaceContracts else {
            return
        }
        guard let reviewClock, reviewClock.isCanonical,
              let nowText = reviewClock.now else {
            throw uiWorldDataCorrupted(decoder, "canonical scenarioContext must declare clock, readerPassage and wordDetail")
        }
        let reviewClockNow = try uiWorldParseCanonicalDate(
            nowText,
            decoder: decoder,
            label: "scenarioContext.reviewClock.now"
        )
        for (fixtureID, seed) in vocabulary {
            for (index, record) in seed.reviewHistory.enumerated()
                where record.reviewedAt > reviewClockNow {
                throw uiWorldDataCorrupted(
                    decoder,
                    "scenarioContext.reviewClock must not precede reviewHistory vocabulary.\(fixtureID).reviewHistory[\(index)]"
                )
            }
        }

        try dictionary.validate(assets: assets, decoder: decoder)
        for (surface, contract) in surfaceContracts {
            try contract.validate(assets: assets, decoder: decoder)
            guard !surface.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                throw uiWorldDataCorrupted(decoder, "surfaceContracts keys must be non-empty")
            }
        }
        guard surfaceContracts["explore"] == sharedDecks.canonicalExploreSurfaceContract else {
            throw uiWorldDataCorrupted(
                decoder,
                "scenarioContext.surfaceContracts.explore must be a projection of top-level sharedDecks; top-level sharedDecks is canonical"
            )
        }
    }
}

struct UIWorldSurfaceContractsSeed: Codable, Equatable {
    let reviewCalendar: UIWorldReviewCalendarEvidenceGroupsSeed?
}

struct UIWorldReviewCalendarEvidenceGroupsSeed: Codable, Equatable {
    let required: [UIWorldReviewCalendarEvidenceSeed]
    let counterexamples: [UIWorldReviewCalendarEvidenceSeed]
}

struct UIWorldReviewCalendarEvidenceSeed: Codable, Equatable {
    let fixtureID: String
    let stepLabel: String
    let index: Int
    let assetIDs: [String]
}

struct UIWorldInstalledFixtureProof: Codable, Equatable {
    let datasetID: String
    let path: String
    let bytes: Int
    let sha256: String
}

/// Reader scenario passage. `activeWord` is the just-tapped word tied to the
/// translation overlay; it is guaranteed to appear as a token in `paragraphs`.
/// `activeWords == [activeWord]`.
struct UIWorldReaderPassageSeed: Codable, Equatable {
    let bookTitle: String
    let activeWord: String
    let activePartOfSpeech: String
    let activeTranslation: String
    let activeExplanation: String
    let activeContext: String
    let paragraphs: [String]
    let vocabWords: [String]
    let activeWords: [String]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case bookTitle
        case activeWord
        case activePartOfSpeech
        case activeTranslation
        case activeExplanation
        case activeContext
        case paragraphs
        case vocabWords
        case activeWords
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World scenarioContext.readerPassage contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }
        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                .init(
                    codingPath: container.codingPath,
                    debugDescription: "UI World scenarioContext.readerPassage must explicitly declare \(key.rawValue)"
                )
            )
        }
        bookTitle = try container.decode(String.self, forKey: .bookTitle)
        activeWord = try container.decode(String.self, forKey: .activeWord)
        activePartOfSpeech = try container.decode(String.self, forKey: .activePartOfSpeech)
        activeTranslation = try container.decode(String.self, forKey: .activeTranslation)
        activeExplanation = try container.decode(String.self, forKey: .activeExplanation)
        activeContext = try container.decode(String.self, forKey: .activeContext)
        paragraphs = try container.decode([String].self, forKey: .paragraphs)
        vocabWords = try container.decode([String].self, forKey: .vocabWords)
        activeWords = try container.decode([String].self, forKey: .activeWords)
    }
}

enum UIWorldPreferenceValue: Codable, Equatable {
    case string(String)
    case double(Double)
    case bool(Bool)

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .double(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else {
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "UI World preference values must be string, number, or bool"
            )
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value):
            try container.encode(value)
        case .double(let value):
            try container.encode(value)
        case .bool(let value):
            try container.encode(value)
        }
    }
}

struct UIWorldPreferencesSeed: Codable, Equatable {
    static let userDefaultsKeys: Set<String> = [
        "activeNotebookId",
        "active_notebook_updated_at",
        "app_appearance_selection",
        "app_language_selection",
        "auto_sync_enabled",
        "hasSeenWelcome",
        "kg_last_incremental_sync",
        "kg_review_payload_version",
        "podcast.autoPauseOnLookup",
        "podcast.subtitleSize",
        "podcast.wordFollowEnabled",
        "reader_settings_font",
        "reader_settings_fontSize",
        "reader_settings_lineHeight",
        "reader_settings_scrollMode",
        "reader_settings_showHitTestingDebug",
        "reader_settings_underlineOpacity",
        "review_settings_autoplay_sound_enabled",
        "review_settings_autoplay_speed",
        "review_settings_custom_params",
        "review_settings_mode",
        "review_settings_mode_updated_at",
        "review_settings_progress_paused",
        "review_settings_progress_paused_at",
        "review_settings_progress_updated_at",
        "translation_source_lang",
        "translation_source_lang_updated_at",
        "translation_target_lang",
        "translation_target_lang_updated_at",
        "vocab_highlight_colorPreset",
        "vocab_highlight_opacity",
    ]
    static let ubiquitousKeyValueStoreKeys: Set<String> = [
        "activeNotebookId",
        "active_notebook_updated_at",
        "app_appearance_selection",
        "app_language_selection",
        "reader_settings_font",
        "reader_settings_fontSize",
        "reader_settings_lineHeight",
        "reader_settings_scrollMode",
        "reader_settings_underlineOpacity",
        "review_settings_custom_params",
        "review_settings_mode",
        "review_settings_mode_updated_at",
        "review_settings_progress_paused",
        "review_settings_progress_paused_at",
        "review_settings_progress_updated_at",
        "translation_source_lang",
        "translation_source_lang_updated_at",
        "translation_target_lang",
        "translation_target_lang_updated_at",
        "vocab_highlight_colorPreset",
        "vocab_highlight_opacity",
    ]

    let userDefaults: [String: UIWorldPreferenceValue]
    let ubiquitousKeyValueStore: [String: UIWorldPreferenceValue]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case userDefaults
        case ubiquitousKeyValueStore
    }

    static let empty = UIWorldPreferencesSeed(userDefaults: [:], ubiquitousKeyValueStore: [:])

    init(
        userDefaults: [String: UIWorldPreferenceValue],
        ubiquitousKeyValueStore: [String: UIWorldPreferenceValue]
    ) {
        self.userDefaults = userDefaults
        self.ubiquitousKeyValueStore = ubiquitousKeyValueStore
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World preferences seed contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                .init(
                    codingPath: container.codingPath,
                    debugDescription: "UI World preferences seed must explicitly declare \(key.rawValue)"
                )
            )
        }
        userDefaults = try container.decode([String: UIWorldPreferenceValue].self, forKey: .userDefaults)
        ubiquitousKeyValueStore = try container.decode([String: UIWorldPreferenceValue].self, forKey: .ubiquitousKeyValueStore)
    }

    var isEmpty: Bool {
        userDefaults.isEmpty && ubiquitousKeyValueStore.isEmpty
    }

    func apply(
        to defaults: UserDefaults = .standard,
        cloud: CloudKeyValueStore = CloudPreferencesSync.shared
    ) {
        for (key, value) in userDefaults {
            precondition(!key.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, "UI World preferences contains an empty UserDefaults key")
            switch value {
            case .string(let string):
                defaults.set(string, forKey: key)
            case .double(let double):
                defaults.set(double, forKey: key)
            case .bool(let bool):
                defaults.set(bool, forKey: key)
            }
        }
        for (key, value) in ubiquitousKeyValueStore {
            precondition(!key.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, "UI World preferences contains an empty iCloud KVS key")
            switch value {
            case .string(let string):
                cloud.set(string, forKey: key)
            case .double(let double):
                cloud.set(double, forKey: key)
            case .bool(let bool):
                cloud.set(bool ? 1.0 : 0.0, forKey: key)
            }
        }
    }
}

struct UIWorldAsset: Codable, Equatable {
    let sourcePath: String
    let sha256: String
    let byteSize: Int
    let installAs: String
    let contentType: String

    enum CodingKeys: String, CodingKey, CaseIterable {
        case sourcePath
        case sha256
        case byteSize
        case installAs
        case contentType
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World asset contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                DecodingError.Context(
                    codingPath: container.codingPath,
                    debugDescription: "UI World asset must explicitly declare \(key.rawValue)"
                )
            )
        }
        sourcePath = try container.decode(String.self, forKey: .sourcePath)
        sha256 = try container.decode(String.self, forKey: .sha256)
        byteSize = try container.decode(Int.self, forKey: .byteSize)
        installAs = try container.decode(String.self, forKey: .installAs)
        contentType = try container.decode(String.self, forKey: .contentType)
        try Self.validateSourcePath(sourcePath, codingPath: container.codingPath)
        try Self.validateSHA256(sha256, codingPath: container.codingPath)
        try Self.validateByteSize(byteSize, codingPath: container.codingPath)
        try Self.validateInstallAs(installAs, codingPath: container.codingPath)
    }

    private static func validateSourcePath(_ sourcePath: String, codingPath: [CodingKey]) throws {
        let trimmed = sourcePath.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: codingPath,
                    debugDescription: "UI World asset sourcePath must be a non-empty path"
                )
            )
        }
        guard !trimmed.hasPrefix("/") else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: codingPath,
                    debugDescription: "UI World asset sourcePath must be repo-relative: \(trimmed)"
                )
            )
        }
        let components = trimmed.split(separator: "/", omittingEmptySubsequences: false).map(String.init)
        guard components.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }) else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: codingPath,
                    debugDescription: "UI World asset sourcePath contains an unsafe path component: \(trimmed)"
                )
            )
        }
    }

    private static func validateSHA256(_ sha256: String, codingPath: [CodingKey]) throws {
        let pattern = #"^[0-9a-f]{64}$"#
        guard sha256.range(of: pattern, options: .regularExpression) != nil else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: codingPath,
                    debugDescription: "UI World asset sha256 must be lowercase 64 hex characters"
                )
            )
        }
    }

    private static func validateByteSize(_ byteSize: Int, codingPath: [CodingKey]) throws {
        guard byteSize > 0 else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: codingPath,
                    debugDescription: "UI World asset byteSize must be a positive integer"
                )
            )
        }
    }

    private static func validateInstallAs(_ installAs: String, codingPath: [CodingKey]) throws {
        let trimmed = installAs.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: codingPath,
                    debugDescription: "UI World asset installAs must be a non-empty relative path"
                )
            )
        }
        guard !trimmed.hasPrefix("/") else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: codingPath,
                    debugDescription: "UI World asset installAs must be relative: \(trimmed)"
                )
            )
        }
        let components = trimmed
            .split(separator: "/", omittingEmptySubsequences: false)
            .map(String.init)
        guard components.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }) else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: codingPath,
                    debugDescription: "UI World asset installAs contains an unsafe path component: \(trimmed)"
                )
            )
        }
    }
}

struct UIWorldAssetManifest: Codable, Equatable {
    private static let contentTypesByBucket: [String: Set<String>] = [
        "books": ["application/epub+zip", "application/pdf", "text/markdown; charset=utf-8", "text/plain; charset=utf-8"],
        "audio": ["audio/mp4", "audio/mpeg"],
        "subtitles": ["application/x-subrip; charset=utf-8", "text/vtt; charset=utf-8"],
        "text": ["text/markdown; charset=utf-8", "text/plain; charset=utf-8"],
        "images": ["image/png", "image/jpeg"],
    ]
    private static let contentTypesByExtension: [String: String] = [
        "epub": "application/epub+zip",
        "pdf": "application/pdf",
        "md": "text/markdown; charset=utf-8",
        "txt": "text/plain; charset=utf-8",
        "m4a": "audio/mp4",
        "mp3": "audio/mpeg",
        "srt": "application/x-subrip; charset=utf-8",
        "vtt": "text/vtt; charset=utf-8",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
    ]

    let books: [String: UIWorldAsset]
    let audio: [String: UIWorldAsset]
    let subtitles: [String: UIWorldAsset]
    let text: [String: UIWorldAsset]
    let images: [String: UIWorldAsset]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case books
        case audio
        case subtitles
        case text
        case images
    }

    init(
        books: [String: UIWorldAsset],
        audio: [String: UIWorldAsset],
        subtitles: [String: UIWorldAsset],
        text: [String: UIWorldAsset],
        images: [String: UIWorldAsset]
    ) {
        self.books = books
        self.audio = audio
        self.subtitles = subtitles
        self.text = text
        self.images = images
    }

    static let empty = UIWorldAssetManifest(
        books: [:],
        audio: [:],
        subtitles: [:],
        text: [:],
        images: [:]
    )

    var isEmpty: Bool {
        books.isEmpty && audio.isEmpty && subtitles.isEmpty && text.isEmpty && images.isEmpty
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World asset manifest contains unknown buckets \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                DecodingError.Context(
                    codingPath: container.codingPath,
                    debugDescription: "UI World asset manifest must explicitly declare \(key.rawValue)"
                )
            )
        }
        books = try container.decode([String: UIWorldAsset].self, forKey: .books)
        audio = try container.decode([String: UIWorldAsset].self, forKey: .audio)
        subtitles = try container.decode([String: UIWorldAsset].self, forKey: .subtitles)
        text = try container.decode([String: UIWorldAsset].self, forKey: .text)
        images = try container.decode([String: UIWorldAsset].self, forKey: .images)
        try Self.validateAssetIDs(
            buckets: [
                "books": books,
                "audio": audio,
                "subtitles": subtitles,
                "text": text,
                "images": images,
            ],
            codingPath: container.codingPath
        )
        try Self.validateUniqueAssetIDs(
            buckets: [
                "books": books,
                "audio": audio,
                "subtitles": subtitles,
                "text": text,
                "images": images,
            ],
            codingPath: container.codingPath
        )
        try Self.validateUniqueInstallPaths(
            buckets: [
                "books": books,
                "audio": audio,
                "subtitles": subtitles,
                "text": text,
                "images": images,
            ],
            codingPath: container.codingPath
        )
        try Self.validateContentTypes(
            buckets: [
                "books": books,
                "audio": audio,
                "subtitles": subtitles,
                "text": text,
                "images": images,
            ],
            codingPath: container.codingPath
        )
    }

    var refs: [String] {
        [
            books.keys.map { "books.\($0)" },
            audio.keys.map { "audio.\($0)" },
            subtitles.keys.map { "subtitles.\($0)" },
            text.keys.map { "text.\($0)" },
            images.keys.map { "images.\($0)" },
        ].flatMap { $0 }.sorted()
    }

    func asset(for ref: String) -> UIWorldAsset? {
        let parts = ref.split(separator: ".", maxSplits: 1).map(String.init)
        guard parts.count == 2 else { return nil }
        switch parts[0] {
        case "books": return books[parts[1]]
        case "audio": return audio[parts[1]]
        case "subtitles": return subtitles[parts[1]]
        case "text": return text[parts[1]]
        case "images": return images[parts[1]]
        default: return nil
        }
    }

    /// Canonical scenario references identify an asset by ID plus its manifest
    /// bucket/type. A duplicated ID across buckets would make that identity
    /// ambiguous, so the decoder rejects it before coverage validation.
    var typeByID: [String: String] {
        var result: [String: String] = [:]
        for (bucket, assets) in [
            ("books", books),
            ("audio", audio),
            ("subtitles", subtitles),
            ("text", text),
            ("images", images),
        ] {
            for assetID in assets.keys {
                result[assetID] = bucket
            }
        }
        return result
    }

    private static func validateAssetIDs(
        buckets: [String: [String: UIWorldAsset]],
        codingPath: [CodingKey]
    ) throws {
        for (bucket, assets) in buckets {
            for assetID in assets.keys {
                guard !assetID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                    throw DecodingError.dataCorrupted(
                        .init(
                            codingPath: codingPath,
                            debugDescription: "UI World asset ID in \(bucket) must be non-empty"
                        )
                    )
                }
            }
        }
    }

    private static func validateUniqueInstallPaths(
        buckets: [String: [String: UIWorldAsset]],
        codingPath: [CodingKey]
    ) throws {
        var seen: [String: String] = [:]
        for (bucket, assets) in buckets {
            for (assetID, asset) in assets {
                let installAs = asset.installAs.trimmingCharacters(in: .whitespacesAndNewlines)
                let ref = "\(bucket).\(assetID)"
                if let previous = seen[installAs] {
                    throw DecodingError.dataCorrupted(
                        .init(
                            codingPath: codingPath,
                            debugDescription: "UI World assets \(previous) and \(ref) share installAs \(installAs)"
                        )
                    )
                }
                seen[installAs] = ref
            }
        }
    }

    private static func validateUniqueAssetIDs(
        buckets: [String: [String: UIWorldAsset]],
        codingPath: [CodingKey]
    ) throws {
        var seen: [String: String] = [:]
        for (bucket, assets) in buckets {
            for assetID in assets.keys {
                let ref = "\(bucket).\(assetID)"
                if let previous = seen[assetID] {
                    throw DecodingError.dataCorrupted(
                        .init(
                            codingPath: codingPath,
                            debugDescription: "UI World asset ID \(assetID) must map to one asset type; found \(previous) and \(ref)"
                        )
                    )
                }
                seen[assetID] = ref
            }
        }
    }

    private static func validateContentTypes(
        buckets: [String: [String: UIWorldAsset]],
        codingPath: [CodingKey]
    ) throws {
        for (bucket, assets) in buckets {
            for (assetID, asset) in assets {
                let ref = "\(bucket).\(assetID)"
                guard contentTypesByBucket[bucket]?.contains(asset.contentType) == true else {
                    throw DecodingError.dataCorrupted(
                        .init(
                            codingPath: codingPath,
                            debugDescription: "UI World asset \(ref) contentType \(asset.contentType) is invalid for \(bucket)"
                        )
                    )
                }
                let installExtension = URL(fileURLWithPath: asset.installAs).pathExtension.lowercased()
                let sourceExtension = URL(fileURLWithPath: asset.sourcePath).pathExtension.lowercased()
                let ext = installExtension.isEmpty ? sourceExtension : installExtension
                if let expected = contentTypesByExtension[ext], asset.contentType != expected {
                    throw DecodingError.dataCorrupted(
                        .init(
                            codingPath: codingPath,
                            debugDescription: "UI World asset \(ref) contentType \(asset.contentType) must match .\(ext) as \(expected)"
                        )
                    )
                }
            }
        }
    }
}

enum UIWorldAuthFixtureID: String, CaseIterable {
    case guest
    case guestAuthenticating
    case guestError
    case signedIn
    case settingsSignedIn
    case longIdentity
}

struct UIWorldAuthSeed: Codable, Equatable {
    enum KeychainTokenState: String, Codable {
        case available
        case readFailed
        case absent
    }

    let isLoggedIn: Bool
    let userId: String?
    let token: String?
    let keychainTokenState: KeychainTokenState
    let displayName: String?
    let email: String?
    let authError: String?
    let isAuthenticating: Bool
    let provider: String?
    let providerUserId: String?

    enum CodingKeys: String, CodingKey, CaseIterable {
        case isLoggedIn
        case userId
        case token
        case keychainTokenState
        case displayName
        case email
        case authError
        case isAuthenticating
        case provider
        case providerUserId
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World auth seed contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                DecodingError.Context(
                    codingPath: container.codingPath,
                    debugDescription: "UI World auth seed must explicitly declare \(key.rawValue), even when null"
                )
            )
        }
        isLoggedIn = try container.decode(Bool.self, forKey: .isLoggedIn)
        userId = try container.decodeIfPresent(String.self, forKey: .userId)
        token = try container.decodeIfPresent(String.self, forKey: .token)
        keychainTokenState = try container.decode(KeychainTokenState.self, forKey: .keychainTokenState)
        displayName = try container.decodeIfPresent(String.self, forKey: .displayName)
        email = try container.decodeIfPresent(String.self, forKey: .email)
        authError = try container.decodeIfPresent(String.self, forKey: .authError)
        isAuthenticating = try container.decode(Bool.self, forKey: .isAuthenticating)
        provider = try container.decodeIfPresent(String.self, forKey: .provider)
        providerUserId = try container.decodeIfPresent(String.self, forKey: .providerUserId)
    }
}

enum UIWorldSyncPresenterFixtureID: String, CaseIterable {
    case ready
    case running
    case completed
    case partialFailure
    case fullFailure
}

struct UIWorldSyncPresenterSeed: Codable, Equatable {
    struct Step: Codable, Equatable {
        let id: String
        let label: String
        let status: String
        let current: Int
        let total: Int
        let detail: String

        enum CodingKeys: String, CodingKey, CaseIterable {
            case id
            case label
            case status
            case current
            case total
            case detail
        }

        init(from decoder: Decoder) throws {
            try UIWorldSyncPresenterSeed.rejectUnknownKeys(
                decoder: decoder,
                keys: CodingKeys.allCases,
                context: "UI World syncPresenter step"
            )
            let container = try decoder.container(keyedBy: CodingKeys.self)
            for key in CodingKeys.allCases where !container.contains(key) {
                throw DecodingError.keyNotFound(
                    key,
                    DecodingError.Context(
                        codingPath: container.codingPath,
                        debugDescription: "UI World syncPresenter step must explicitly declare \(key.rawValue)"
                    )
                )
            }
            id = try container.decode(String.self, forKey: .id)
            label = try container.decode(String.self, forKey: .label)
            status = try container.decode(String.self, forKey: .status)
            current = try container.decode(Int.self, forKey: .current)
            total = try container.decode(Int.self, forKey: .total)
            detail = try container.decode(String.self, forKey: .detail)
        }
    }

    struct PendingRow: Codable, Equatable {
        let id: String
        let word: String
        let partOfSpeech: String?
        let translation: String
        let wordTone: String
        let isStrikethrough: Bool
        let actionSystemImage: String
        let actionTone: String
        let actionAccessibilityLabel: String

        enum CodingKeys: String, CodingKey, CaseIterable {
            case id
            case word
            case partOfSpeech
            case translation
            case wordTone
            case isStrikethrough
            case actionSystemImage
            case actionTone
            case actionAccessibilityLabel
        }

        init(from decoder: Decoder) throws {
            try UIWorldSyncPresenterSeed.rejectUnknownKeys(
                decoder: decoder,
                keys: CodingKeys.allCases,
                context: "UI World syncPresenter pending row"
            )
            let container = try decoder.container(keyedBy: CodingKeys.self)
            for key in CodingKeys.allCases where !container.contains(key) {
                throw DecodingError.keyNotFound(
                    key,
                    DecodingError.Context(
                        codingPath: container.codingPath,
                        debugDescription: "UI World syncPresenter pending row must explicitly declare \(key.rawValue)"
                    )
                )
            }
            id = try container.decode(String.self, forKey: .id)
            word = try container.decode(String.self, forKey: .word)
            partOfSpeech = try container.decodeIfPresent(String.self, forKey: .partOfSpeech)
            translation = try container.decode(String.self, forKey: .translation)
            wordTone = try container.decode(String.self, forKey: .wordTone)
            isStrikethrough = try container.decode(Bool.self, forKey: .isStrikethrough)
            actionSystemImage = try container.decode(String.self, forKey: .actionSystemImage)
            actionTone = try container.decode(String.self, forKey: .actionTone)
            actionAccessibilityLabel = try container.decode(String.self, forKey: .actionAccessibilityLabel)
        }
    }

    let isLoggedIn: Bool
    let isConnected: Bool
    let phase: String
    let failureKind: String?
    let pendingCount: Int
    let addCount: Int
    let deleteCount: Int
    let steps: [Step]
    let summaryText: String
    let pendingRows: [PendingRow]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case isLoggedIn
        case isConnected
        case phase
        case failureKind
        case pendingCount
        case addCount
        case deleteCount
        case steps
        case summaryText
        case pendingRows
    }

    init(from decoder: Decoder) throws {
        try Self.rejectUnknownKeys(
            decoder: decoder,
            keys: CodingKeys.allCases,
            context: "UI World syncPresenter seed"
        )
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try Self.requireAllKeys(in: container, context: "UI World syncPresenter seed")
        isLoggedIn = try container.decode(Bool.self, forKey: .isLoggedIn)
        isConnected = try container.decode(Bool.self, forKey: .isConnected)
        phase = try container.decode(String.self, forKey: .phase)
        failureKind = try container.decodeIfPresent(String.self, forKey: .failureKind)
        pendingCount = try container.decode(Int.self, forKey: .pendingCount)
        addCount = try container.decode(Int.self, forKey: .addCount)
        deleteCount = try container.decode(Int.self, forKey: .deleteCount)
        steps = try container.decode([Step].self, forKey: .steps)
        summaryText = try container.decode(String.self, forKey: .summaryText)
        pendingRows = try container.decode([PendingRow].self, forKey: .pendingRows)
    }

    fileprivate static func rejectUnknownKeys<K: CodingKey & RawRepresentable>(
        decoder: Decoder,
        keys: [K],
        context: String
    ) throws where K.RawValue == String {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(keys.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "\(context) contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }
    }

    private static func requireAllKeys<C: KeyedDecodingContainerProtocol>(
        in container: C,
        context: String
    ) throws where C.Key: CaseIterable & RawRepresentable, C.Key.RawValue == String {
        for key in C.Key.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                DecodingError.Context(
                    codingPath: container.codingPath,
                    debugDescription: "\(context) must explicitly declare \(key.rawValue)"
                )
            )
        }
    }
}

enum UIWorldEntitlementsFixtureID: String, CaseIterable {
    case adminGranted
    case cancelledButActive
    case free
    case pro
}

struct UIWorldEntitlementsSeed: Codable, Equatable {
    let pro: KGSubscriptionStatus

    enum CodingKeys: String, CodingKey, CaseIterable {
        case pro
    }

    private enum ProCodingKeys: String, CodingKey, CaseIterable {
        case is_active
        case product_id
        case plan_name
        case price_display
        case status
        case is_trial
        case trial_days
        case will_renew
        case expires_at
        case source
        case last_synced_at
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World entitlements seed contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                .init(
                    codingPath: container.codingPath,
                    debugDescription: "UI World entitlements seed must explicitly declare \(key.rawValue)"
                )
            )
        }

        let rawProContainer = try container.nestedContainer(keyedBy: AnyCodingKey.self, forKey: .pro)
        let unknownProKeys = Set(rawProContainer.allKeys.map(\.stringValue))
            .subtracting(ProCodingKeys.allCases.map(\.rawValue))
        guard unknownProKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: rawProContainer.codingPath,
                    debugDescription: "UI World entitlements pro status contains unknown keys \(unknownProKeys.sorted())"
                )
            )
        }

        let proContainer = try container.nestedContainer(keyedBy: ProCodingKeys.self, forKey: .pro)
        for key in ProCodingKeys.allCases where !proContainer.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                .init(
                    codingPath: proContainer.codingPath,
                    debugDescription: "UI World entitlements pro status must explicitly declare \(key.rawValue), even when null"
                )
            )
        }

        pro = try container.decode(KGSubscriptionStatus.self, forKey: .pro)
    }
}

enum UIWorldRuntimePodcastFixtureID: String, CaseIterable {
    case playablePreview
    case tieredCatalog
}

struct UIWorldRuntimePodcastEpisodeSeed: Codable, Equatable {
    struct Download: Codable, Equatable {
        let audioAssetRef: String
        let subtitleAssetRef: String?
        let localAudioPath: String
        let localSubtitlePath: String?

        enum CodingKeys: String, CodingKey, CaseIterable {
            case audioAssetRef
            case subtitleAssetRef
            case localAudioPath
            case localSubtitlePath
        }

        init(
            audioAssetRef: String,
            subtitleAssetRef: String?,
            localAudioPath: String,
            localSubtitlePath: String?
        ) {
            self.audioAssetRef = audioAssetRef
            self.subtitleAssetRef = subtitleAssetRef
            self.localAudioPath = localAudioPath
            self.localSubtitlePath = localSubtitlePath
        }

        init(from decoder: Decoder) throws {
            let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
            let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
                .subtracting(CodingKeys.allCases.map(\.rawValue))
            guard unknownKeys.isEmpty else {
                throw DecodingError.dataCorrupted(
                    .init(
                        codingPath: decoder.codingPath,
                        debugDescription: "UI World runtime podcast download contains unknown keys \(unknownKeys.sorted())"
                    )
                )
            }

            let container = try decoder.container(keyedBy: CodingKeys.self)
            for key in CodingKeys.allCases where !container.contains(key) {
                throw DecodingError.keyNotFound(
                    key,
                    .init(
                        codingPath: decoder.codingPath,
                        debugDescription: "UI World runtime podcast download must explicitly declare \(key.rawValue)"
                    )
                )
            }

            audioAssetRef = try container.decode(String.self, forKey: .audioAssetRef)
            subtitleAssetRef = try container.decodeIfPresent(String.self, forKey: .subtitleAssetRef)
            localAudioPath = try container.decode(String.self, forKey: .localAudioPath)
            localSubtitlePath = try container.decodeIfPresent(String.self, forKey: .localSubtitlePath)
        }
    }

    let remoteId: String
    let episodeNumber: Int
    let title: String
    let durationSec: Double
    let audioAvailable: Bool
    let previewAvailable: Bool
    let previewDurationSec: Double
    let subtitleAvailable: Bool
    let download: Download?

    enum CodingKeys: String, CodingKey, CaseIterable {
        case remoteId
        case episodeNumber
        case title
        case durationSec
        case audioAvailable
        case previewAvailable
        case previewDurationSec
        case subtitleAvailable
        case download
    }

    init(
        remoteId: String,
        episodeNumber: Int,
        title: String,
        durationSec: Double,
        audioAvailable: Bool,
        previewAvailable: Bool,
        previewDurationSec: Double,
        subtitleAvailable: Bool,
        download: Download?
    ) {
        self.remoteId = remoteId
        self.episodeNumber = episodeNumber
        self.title = title
        self.durationSec = durationSec
        self.audioAvailable = audioAvailable
        self.previewAvailable = previewAvailable
        self.previewDurationSec = previewDurationSec
        self.subtitleAvailable = subtitleAvailable
        self.download = download
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World runtime podcast episode contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World runtime podcast episode must explicitly declare \(key.rawValue)"
                )
            )
        }

        remoteId = try container.decode(String.self, forKey: .remoteId)
        episodeNumber = try container.decode(Int.self, forKey: .episodeNumber)
        title = try container.decode(String.self, forKey: .title)
        durationSec = try container.decode(Double.self, forKey: .durationSec)
        audioAvailable = try container.decode(Bool.self, forKey: .audioAvailable)
        previewAvailable = try container.decode(Bool.self, forKey: .previewAvailable)
        previewDurationSec = try container.decode(Double.self, forKey: .previewDurationSec)
        subtitleAvailable = try container.decode(Bool.self, forKey: .subtitleAvailable)
        download = try container.decodeIfPresent(Download.self, forKey: .download)
    }
}

struct UIWorldRuntimePodcastSeed: Codable, Equatable {
    let audioAssetRef: String
    let subtitleAssetRef: String
    let seriesRemoteId: String
    let seriesTitle: String
    let hostNames: [String]
    let preferredNotebookId: String?
    let color: String?
    let coverPattern: String?
    let sortOrder: Int
    let durationSec: Double
    let episodes: [UIWorldRuntimePodcastEpisodeSeed]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case audioAssetRef
        case subtitleAssetRef
        case seriesRemoteId
        case seriesTitle
        case hostNames
        case preferredNotebookId
        case color
        case coverPattern
        case sortOrder
        case durationSec
        case episodes
    }

    init(
        audioAssetRef: String,
        subtitleAssetRef: String,
        seriesRemoteId: String,
        seriesTitle: String,
        hostNames: [String],
        preferredNotebookId: String?,
        color: String?,
        coverPattern: String?,
        sortOrder: Int,
        durationSec: Double,
        episodes: [UIWorldRuntimePodcastEpisodeSeed]
    ) {
        self.audioAssetRef = audioAssetRef
        self.subtitleAssetRef = subtitleAssetRef
        self.seriesRemoteId = seriesRemoteId
        self.seriesTitle = seriesTitle
        self.hostNames = hostNames
        self.preferredNotebookId = preferredNotebookId
        self.color = color
        self.coverPattern = coverPattern
        self.sortOrder = sortOrder
        self.durationSec = durationSec
        self.episodes = episodes
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World runtime podcast series contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World runtime podcast series must explicitly declare \(key.rawValue)"
                )
            )
        }

        audioAssetRef = try container.decode(String.self, forKey: .audioAssetRef)
        subtitleAssetRef = try container.decode(String.self, forKey: .subtitleAssetRef)
        seriesRemoteId = try container.decode(String.self, forKey: .seriesRemoteId)
        seriesTitle = try container.decode(String.self, forKey: .seriesTitle)
        hostNames = try container.decode([String].self, forKey: .hostNames)
        preferredNotebookId = try container.decodeIfPresent(String.self, forKey: .preferredNotebookId)
        color = try container.decodeIfPresent(String.self, forKey: .color)
        coverPattern = try container.decodeIfPresent(String.self, forKey: .coverPattern)
        sortOrder = try container.decode(Int.self, forKey: .sortOrder)
        durationSec = try container.decode(Double.self, forKey: .durationSec)
        episodes = try container.decode([UIWorldRuntimePodcastEpisodeSeed].self, forKey: .episodes)
    }
}

enum UIWorldReaderFixtureID: String, CaseIterable {
    case realBookLibrary
    case invalidDestinationLibrary
}

struct UIWorldReaderSeed: Codable, Equatable {
    let textAssetRef: String
    let bookAssetRef: String
    let title: String
    let author: String
    let bookFileName: String
    let notebookRemoteId: String
    let notebookName: String
    let notebookSyncStatus: Int
    let entry: UIWorldVocabularyEntrySeed

    enum CodingKeys: String, CodingKey, CaseIterable {
        case textAssetRef
        case bookAssetRef
        case title
        case author
        case bookFileName
        case notebookRemoteId
        case notebookName
        case notebookSyncStatus
        case entry
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World reader seed contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                .init(
                    codingPath: container.codingPath,
                    debugDescription: "UI World reader seed must explicitly declare \(key.rawValue)"
                )
            )
        }
        textAssetRef = try container.decode(String.self, forKey: .textAssetRef)
        bookAssetRef = try container.decode(String.self, forKey: .bookAssetRef)
        title = try container.decode(String.self, forKey: .title)
        author = try container.decode(String.self, forKey: .author)
        bookFileName = try container.decode(String.self, forKey: .bookFileName)
        notebookRemoteId = try container.decode(String.self, forKey: .notebookRemoteId)
        notebookName = try container.decode(String.self, forKey: .notebookName)
        notebookSyncStatus = try container.decode(Int.self, forKey: .notebookSyncStatus)
        entry = try container.decode(UIWorldVocabularyEntrySeed.self, forKey: .entry)
    }
}

enum UIWorldVocabularyFixtureID: String, CaseIterable {
    case archivedEmpty
    case archivedLong
    case archivedPopulated
    case archivedSingle
    case knowledgeGraphEmpty
    case knowledgeGraphPopulated
    case kgVocabRow
    case reviewCalendarDense
    case searchVocabNotebook
    case shellNavigation
    case statsEmpty
    case statsPopulated
    case syncEmpty
    case syncPendingMixed
    case syncPendingSingle
    case vocabLinkedCards
    case vocabListEmpty
    case vocabListLong
    case vocabListPopulated
    case vocabListSingle
    case vocabListSyncing
    case p11ReviewMix = "p11.644.reviewMix"
    case roleMixed = "role.mixed"
    case wordDetail
    case wordEdit
}

struct UIWorldVocabularySeed: Codable, Equatable {
    let notebookRemoteId: String
    let notebookName: String
    let notebookSyncStatus: Int
    let bookTitle: String
    let entries: [UIWorldVocabularyEntrySeed]
    let reviewHistory: [UIWorldReviewHistorySeed]
    let baseFixture: String?
    let entryOverrides: [UIWorldVocabularyEntryOverride]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case notebookRemoteId
        case notebookName
        case notebookSyncStatus
        case bookTitle
        case entries
        case reviewHistory
        case baseFixture
        case entryOverrides
    }

    private static let optionalCodingKeys: Set<String> = [
        CodingKeys.baseFixture.rawValue,
        CodingKeys.entryOverrides.rawValue,
    ]

    init(
        notebookRemoteId: String,
        notebookName: String,
        notebookSyncStatus: Int,
        bookTitle: String,
        entries: [UIWorldVocabularyEntrySeed],
        reviewHistory: [UIWorldReviewHistorySeed],
        baseFixture: String? = nil,
        entryOverrides: [UIWorldVocabularyEntryOverride] = []
    ) {
        self.notebookRemoteId = notebookRemoteId
        self.notebookName = notebookName
        self.notebookSyncStatus = notebookSyncStatus
        self.bookTitle = bookTitle
        self.entries = entries
        self.reviewHistory = reviewHistory
        self.baseFixture = baseFixture
        self.entryOverrides = entryOverrides
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World vocabulary seed contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases
            where !Self.optionalCodingKeys.contains(key.rawValue) && !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                .init(
                    codingPath: container.codingPath,
                    debugDescription: "UI World vocabulary seed must explicitly declare \(key.rawValue)"
                )
            )
        }
        notebookRemoteId = try container.decode(String.self, forKey: .notebookRemoteId)
        notebookName = try container.decode(String.self, forKey: .notebookName)
        notebookSyncStatus = try container.decode(Int.self, forKey: .notebookSyncStatus)
        bookTitle = try container.decode(String.self, forKey: .bookTitle)
        entries = try container.decode([UIWorldVocabularyEntrySeed].self, forKey: .entries)
        reviewHistory = try container.decode([UIWorldReviewHistorySeed].self, forKey: .reviewHistory)
        baseFixture = try container.decodeIfPresent(String.self, forKey: .baseFixture)
        entryOverrides = try container.decodeIfPresent(
            [UIWorldVocabularyEntryOverride].self,
            forKey: .entryOverrides
        ) ?? []
    }
}

struct UIWorldVocabularyEntryOverride: Codable, Equatable {
    let word: String
    let cardRole: VocabularyCardRole
    let reviewEligible: Bool
    let reviewIntervalHours: Double
    let nextReviewAt: Date
    let lastReviewedAt: Date?
    let reviewCount: Int
    let reviewStreak: Int
    let lastReviewFeedbackRaw: Int

    enum CodingKeys: String, CodingKey, CaseIterable {
        case word
        case cardRole
        case reviewEligible
        case reviewIntervalHours
        case nextReviewAt
        case lastReviewedAt
        case reviewCount
        case reviewStreak
        case lastReviewFeedbackRaw
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World vocabulary entry override contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                .init(
                    codingPath: container.codingPath,
                    debugDescription: "UI World vocabulary entry override must explicitly declare \(key.rawValue)"
                )
            )
        }

        word = try container.decode(String.self, forKey: .word)
        cardRole = try container.decode(VocabularyCardRole.self, forKey: .cardRole)
        reviewEligible = try container.decode(Bool.self, forKey: .reviewEligible)
        reviewIntervalHours = try container.decode(Double.self, forKey: .reviewIntervalHours)
        nextReviewAt = try container.decode(Date.self, forKey: .nextReviewAt)
        lastReviewedAt = try container.decodeIfPresent(Date.self, forKey: .lastReviewedAt)
        reviewCount = try container.decode(Int.self, forKey: .reviewCount)
        reviewStreak = try container.decode(Int.self, forKey: .reviewStreak)
        lastReviewFeedbackRaw = try container.decode(Int.self, forKey: .lastReviewFeedbackRaw)
    }
}

struct UIWorldReviewHistorySeed: Codable, Equatable {
    let word: String
    let feedback: Int
    let reviewedAt: Date

    enum CodingKeys: String, CodingKey, CaseIterable {
        case word
        case feedback
        case reviewedAt
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World review history contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                .init(
                    codingPath: container.codingPath,
                    debugDescription: "UI World review history must explicitly declare \(key.rawValue)"
                )
            )
        }
        word = try container.decode(String.self, forKey: .word)
        feedback = try container.decode(Int.self, forKey: .feedback)
        reviewedAt = try container.decode(Date.self, forKey: .reviewedAt)
    }
}

enum UIWorldReviewDeckFixtureID: String, CaseIterable {
    case phaseLongContent
    case phaseMulti
    case phaseSingle
    case probe
    case notebookReviewDeck
}

struct UIWorldReviewDeckSeed: Codable, Equatable {
    let notebookRemoteId: String
    let notebookName: String
    let notebookSyncStatus: Int
    let entries: [UIWorldVocabularyEntrySeed]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case notebookRemoteId
        case notebookName
        case notebookSyncStatus
        case entries
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World review deck seed contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                .init(
                    codingPath: container.codingPath,
                    debugDescription: "UI World review deck seed must explicitly declare \(key.rawValue)"
                )
            )
        }
        notebookRemoteId = try container.decode(String.self, forKey: .notebookRemoteId)
        notebookName = try container.decode(String.self, forKey: .notebookName)
        notebookSyncStatus = try container.decode(Int.self, forKey: .notebookSyncStatus)
        entries = try container.decode([UIWorldVocabularyEntrySeed].self, forKey: .entries)
    }
}

struct UIWorldVocabularyEntrySeed: Codable, Equatable {
    let word: String
    let translation: String
    let context: String
    let explanation: String?
    let partOfSpeech: String?
    let bookTitle: String
    let chapterTitle: String?
    let kgCardId: String?
    let difficultyTier: String?
    let reviewMode: VocabularyCardMode
    let reviewExamples: [String]
    let collocations: [String]?
    let rootForm: String?
    let inflections: [String]?
    let syncStatus: Int
    let actionType: String
    let isArchived: Bool
    let isExcludedFromReader: Bool
    let reviewIntervalHours: Double?
    let nextReviewAt: Date?
    let lastReviewedAt: Date?
    let reviewCount: Int?
    let reviewStreak: Int?
    let lastReviewFeedbackRaw: Int?
    let graphLinksByKind: [String: [KGCardLinkSummary]]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case word
        case translation
        case context
        case explanation
        case partOfSpeech
        case bookTitle
        case chapterTitle
        case kgCardId
        case difficultyTier
        case reviewMode
        case reviewExamples
        case collocations
        case rootForm
        case inflections
        case syncStatus
        case actionType
        case isArchived
        case isExcludedFromReader
        case reviewIntervalHours
        case nextReviewAt
        case lastReviewedAt
        case reviewCount
        case reviewStreak
        case lastReviewFeedbackRaw
        case graphLinksByKind
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World vocabulary entry contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World vocabulary entry must explicitly declare \(key.rawValue)"
                )
            )
        }

        word = try container.decode(String.self, forKey: .word)
        translation = try container.decode(String.self, forKey: .translation)
        context = try container.decode(String.self, forKey: .context)
        explanation = try container.decodeIfPresent(String.self, forKey: .explanation)
        partOfSpeech = try container.decodeIfPresent(String.self, forKey: .partOfSpeech)
        bookTitle = try container.decode(String.self, forKey: .bookTitle)
        chapterTitle = try container.decodeIfPresent(String.self, forKey: .chapterTitle)
        kgCardId = try container.decodeIfPresent(String.self, forKey: .kgCardId)
        difficultyTier = try container.decodeIfPresent(String.self, forKey: .difficultyTier)
        reviewMode = try container.decode(VocabularyCardMode.self, forKey: .reviewMode)
        reviewExamples = try container.decode([String].self, forKey: .reviewExamples)
        collocations = try container.decodeIfPresent([String].self, forKey: .collocations)
        rootForm = try container.decodeIfPresent(String.self, forKey: .rootForm)
        inflections = try container.decodeIfPresent([String].self, forKey: .inflections)
        syncStatus = try container.decode(Int.self, forKey: .syncStatus)
        actionType = try container.decode(String.self, forKey: .actionType)
        isArchived = try container.decode(Bool.self, forKey: .isArchived)
        isExcludedFromReader = try container.decode(Bool.self, forKey: .isExcludedFromReader)
        reviewIntervalHours = try container.decodeIfPresent(Double.self, forKey: .reviewIntervalHours)
        nextReviewAt = try container.decodeIfPresent(Date.self, forKey: .nextReviewAt)
        lastReviewedAt = try container.decodeIfPresent(Date.self, forKey: .lastReviewedAt)
        reviewCount = try container.decodeIfPresent(Int.self, forKey: .reviewCount)
        reviewStreak = try container.decodeIfPresent(Int.self, forKey: .reviewStreak)
        lastReviewFeedbackRaw = try container.decodeIfPresent(Int.self, forKey: .lastReviewFeedbackRaw)
        graphLinksByKind = try container.decode([String: [KGCardLinkSummary]].self, forKey: .graphLinksByKind)
    }
}
