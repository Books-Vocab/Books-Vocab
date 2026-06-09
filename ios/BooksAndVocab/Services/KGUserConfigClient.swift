import Foundation

protocol KGUserConfigRemoteHandling {
    func fetchUserConfig(baseURL: URL, token: String) async throws -> KGUserConfig
    func updateTranslationConfig(baseURL: URL, token: String, translation: KGTranslationConfig) async throws -> KGUserConfig
    func updateReviewClockConfig(baseURL: URL, token: String, reviewClock: KGReviewClockConfig) async throws -> KGUserConfig
    func updateReviewModeConfig(baseURL: URL, token: String, reviewMode: KGReviewModeConfig) async throws -> KGUserConfig
    func updateVocabUIConfig(baseURL: URL, token: String, vocabUI: KGVocabUIConfig) async throws -> KGUserConfig
}

/// PUT /api/user/config 的 partial patch。後端各欄位獨立 optional(不送=不更新),
/// 故只 encode 有值的欄位(encodeIfPresent),避免送 null 造成「覆寫 vs 略過」語意混淆。
private struct KGUserConfigPatch: Encodable {
    let translation: KGTranslationConfig?
    let review_clock: KGReviewClockConfig?
    let review_mode: KGReviewModeConfig?
    let vocab_ui: KGVocabUIConfig?

    enum CodingKeys: String, CodingKey {
        case translation
        case review_clock
        case review_mode
        case vocab_ui
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encodeIfPresent(translation, forKey: .translation)
        try c.encodeIfPresent(review_clock, forKey: .review_clock)
        try c.encodeIfPresent(review_mode, forKey: .review_mode)
        try c.encodeIfPresent(vocab_ui, forKey: .vocab_ui)
    }
}

final class KGUserConfigClient: KGUserConfigRemoteHandling {
    func fetchUserConfig(baseURL: URL, token: String) async throws -> KGUserConfig {
        var request = URLRequest(url: baseURL.appendingPathComponent("api/user/config"))
        Self.applyAuth(to: &request, token: token)
        return try await perform(request)
    }

    func updateTranslationConfig(baseURL: URL, token: String, translation: KGTranslationConfig) async throws -> KGUserConfig {
        let patch = KGUserConfigPatch(translation: translation, review_clock: nil, review_mode: nil, vocab_ui: nil)
        return try await update(baseURL: baseURL, token: token, patch: patch)
    }

    func updateReviewClockConfig(baseURL: URL, token: String, reviewClock: KGReviewClockConfig) async throws -> KGUserConfig {
        let patch = KGUserConfigPatch(translation: nil, review_clock: reviewClock, review_mode: nil, vocab_ui: nil)
        return try await update(baseURL: baseURL, token: token, patch: patch)
    }

    func updateReviewModeConfig(baseURL: URL, token: String, reviewMode: KGReviewModeConfig) async throws -> KGUserConfig {
        let patch = KGUserConfigPatch(translation: nil, review_clock: nil, review_mode: reviewMode, vocab_ui: nil)
        return try await update(baseURL: baseURL, token: token, patch: patch)
    }

    func updateVocabUIConfig(baseURL: URL, token: String, vocabUI: KGVocabUIConfig) async throws -> KGUserConfig {
        let patch = KGUserConfigPatch(translation: nil, review_clock: nil, review_mode: nil, vocab_ui: vocabUI)
        return try await update(baseURL: baseURL, token: token, patch: patch)
    }

    private func update(baseURL: URL, token: String, patch: KGUserConfigPatch) async throws -> KGUserConfig {
        var request = URLRequest(url: baseURL.appendingPathComponent("api/user/config"))
        request.httpMethod = "PUT"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        Self.applyAuth(to: &request, token: token)
        request.httpBody = try JSONEncoder().encode(patch)
        return try await perform(request)
    }

    private static func applyAuth(to request: inout URLRequest, token: String) {
        request.addValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        _ = RequestObservation.attachRequestID(to: &request)
    }

    private func perform(_ request: URLRequest) async throws -> KGUserConfig {
        let (data, response) = try await withRetry { try await sharedURLSession.data(for: request) }
        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }
        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard (200...299).contains(httpResponse.statusCode) else {
            throw KGError.httpError(statusCode: httpResponse.statusCode, detail: "user config request failed")
        }
        return try JSONDecoder().decode(KGUserConfig.self, from: data)
    }
}
