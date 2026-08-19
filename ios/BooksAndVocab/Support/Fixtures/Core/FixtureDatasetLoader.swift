import Foundation

enum FixtureDatasetLoader {
    static let datasetEnvironmentKey = "KG_FIXTURE_DATASET_B64"
    static let deflateEnvironmentKey = "KG_FIXTURE_DATASET_DEFLATE_B64"

    enum Source {
        case absent
        case invalid(source: String, error: String)
        case data(Data, description: String)
    }

    static func loadSource(
        testingOverrideData: Data?,
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> Source {
        if let testingOverrideData {
            return .data(testingOverrideData, description: "testing-override")
        }

        let deflateRawValue = environment[deflateEnvironmentKey]
        let plainRawValue = environment[datasetEnvironmentKey]

        if deflateRawValue != nil, plainRawValue != nil {
            // Two sources could describe two different worlds; picking one
            // silently would hide tooling drift.
            return .invalid(
                source: "env:\(deflateEnvironmentKey)+\(datasetEnvironmentKey)",
                error: "both \(deflateEnvironmentKey) and \(datasetEnvironmentKey) are set; the UI World source is ambiguous — unset one"
            )
        }

        if let deflateRawValue {
            let envDescription = "env:\(deflateEnvironmentKey)"
            guard !deflateRawValue.isEmpty else {
                return .invalid(source: envDescription, error: "\(deflateEnvironmentKey) must not be empty")
            }
            guard let compressed = Data(base64Encoded: deflateRawValue) else {
                return .invalid(source: envDescription, error: "\(deflateEnvironmentKey) is not valid base64")
            }
            do {
                let data = try (compressed as NSData).decompressed(using: .zlib) as Data
                return .data(data, description: envDescription)
            } catch {
                return .invalid(
                    source: envDescription,
                    error: "\(deflateEnvironmentKey) is not a raw DEFLATE stream (decompress failed: \(error.localizedDescription))"
                )
            }
        }

        let envDescription = "env:\(datasetEnvironmentKey)"
        guard let rawValue = plainRawValue else {
            return .absent
        }
        guard !rawValue.isEmpty else {
            return .invalid(source: envDescription, error: "\(datasetEnvironmentKey) must not be empty")
        }
        guard let data = Data(base64Encoded: rawValue) else {
            return .invalid(source: envDescription, error: "\(datasetEnvironmentKey) is not valid base64")
        }
        return .data(data, description: envDescription)
    }

    static func decode(_ data: Data) throws -> FixtureDatasetDocument {
        try makeDecoder().decode(FixtureDatasetDocument.self, from: data)
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
