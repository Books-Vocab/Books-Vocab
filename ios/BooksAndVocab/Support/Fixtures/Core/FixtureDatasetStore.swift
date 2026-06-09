import Foundation

private let fixtureDatasetEnvKey = "KG_FIXTURE_DATASET_B64"
private let fixtureDatasetFilePath = "/tmp/kg-fixture-dataset.json"

struct FixtureDatasetDocument: Decodable {
    let schema: String?
    let datasetID: String?
    let settings: [String: SettingsFixtureSeed]
    let bookshelf: [String: BookshelfFixtureSeed]
    let todayReview: [String: TodayReviewSessionSeed]

    private enum CodingKeys: String, CodingKey {
        case schema
        case datasetID
        case settings
        case bookshelf
        case todayReview
    }

    init(
        schema: String? = nil,
        datasetID: String? = nil,
        settings: [String: SettingsFixtureSeed] = [:],
        bookshelf: [String: BookshelfFixtureSeed] = [:],
        todayReview: [String: TodayReviewSessionSeed] = [:]
    ) {
        self.schema = schema
        self.datasetID = datasetID
        self.settings = settings
        self.bookshelf = bookshelf
        self.todayReview = todayReview
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        schema = try container.decodeIfPresent(String.self, forKey: .schema)
        datasetID = try container.decodeIfPresent(String.self, forKey: .datasetID)
        settings = try container.decodeIfPresent([String: SettingsFixtureSeed].self, forKey: .settings) ?? [:]
        bookshelf = try container.decodeIfPresent([String: BookshelfFixtureSeed].self, forKey: .bookshelf) ?? [:]
        todayReview = try container.decodeIfPresent([String: TodayReviewSessionSeed].self, forKey: .todayReview) ?? [:]
    }
}

enum FixtureDatasetStore {
    static var testingOverrideData: Data?

    static func withTestingData<T>(_ data: Data?, perform: () throws -> T) rethrows -> T {
        let previous = testingOverrideData
        testingOverrideData = data
        defer { testingOverrideData = previous }
        return try perform()
    }

    static func settingsSeed(for fixtureID: SettingsFixtureID) -> SettingsFixtureSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.settings[fixtureID.rawValue]
    }

    static func bookshelfSeed(for fixtureID: BookshelfFixtureID) -> BookshelfFixtureSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.bookshelf[fixtureID.rawValue]
    }

    static func todayReviewSeed(for fixtureID: TodayReviewFixtureID) -> TodayReviewSessionSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.todayReview[fixtureID.rawValue]
    }

    static func debugSummary() -> String {
        switch loadState() {
        case .absent:
            return "absent"
        case let .invalid(source, error):
            return "invalid @ \(source) (\(error))"
        case let .loaded(document, source):
            return "\(document.datasetID ?? "<no-id>") @ \(source)"
        }
    }

    private enum LoadState {
        case absent
        case invalid(source: String, error: String)
        case loaded(FixtureDatasetDocument, source: String)
    }

    private static func loadState() -> LoadState {
        guard let source = loadSource() else { return .absent }
        do {
            let document = try makeDecoder().decode(FixtureDatasetDocument.self, from: source.data)
            return .loaded(document, source: source.description)
        } catch {
            return .invalid(source: source.description, error: error.localizedDescription)
        }
    }

    private static func loadSource() -> (data: Data, description: String)? {
        if let testingOverrideData {
            return (testingOverrideData, "testing-override")
        }

        if let rawValue = ProcessInfo.processInfo.environment[fixtureDatasetEnvKey],
           let data = Data(base64Encoded: rawValue) {
            return (data, "env:\(fixtureDatasetEnvKey)")
        }

        let url = URL(fileURLWithPath: fixtureDatasetFilePath)
        if let data = try? Data(contentsOf: url) {
            return (data, fixtureDatasetFilePath)
        }

        return nil
    }

    private static func makeDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            if let rawValue = try? container.decode(String.self) {
                if let date = AppDateFormatters.parseISO8601(rawValue) {
                    return date
                }
                throw DecodingError.dataCorruptedError(
                    in: container,
                    debugDescription: "Expected ISO8601 date string, got \(rawValue)"
                )
            }
            if let rawValue = try? container.decode(Double.self) {
                return Date(timeIntervalSince1970: rawValue)
            }
            if let rawValue = try? container.decode(Int.self) {
                return Date(timeIntervalSince1970: TimeInterval(rawValue))
            }
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Expected ISO8601 string or epoch seconds for Date"
            )
        }
        return decoder
    }
}

extension SubscriptionBadgeTone: Codable {
    private enum EncodedValue: String, Codable {
        case neutral
        case accent
        case success
    }

    init(from decoder: Decoder) throws {
        switch try EncodedValue(from: decoder) {
        case .neutral:
            self = .neutral
        case .accent:
            self = .accent
        case .success:
            self = .success
        }
    }

    func encode(to encoder: Encoder) throws {
        let encodedValue: EncodedValue
        switch self {
        case .neutral:
            encodedValue = .neutral
        case .accent:
            encodedValue = .accent
        case .success:
            encodedValue = .success
        }
        try encodedValue.encode(to: encoder)
    }
}

extension AutoplaySpeed: Codable {}

extension TodayReviewRevealStage: Codable {
    private enum EncodedValue: String, Codable {
        case front
        case back
    }

    init(from decoder: Decoder) throws {
        switch try EncodedValue(from: decoder) {
        case .front:
            self = .front
        case .back:
            self = .back
        }
    }

    func encode(to encoder: Encoder) throws {
        let encodedValue: EncodedValue = self == .front ? .front : .back
        try encodedValue.encode(to: encoder)
    }
}
