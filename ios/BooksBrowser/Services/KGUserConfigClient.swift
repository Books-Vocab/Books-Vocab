import Foundation

protocol KGUserConfigRemoteHandling {
    func fetchUserConfig(baseURL: URL, token: String) async throws -> KGUserConfig
    func updateOptionalIntegrationKey(baseURL: URL, token: String, apiKey: String) async throws -> KGUserConfig
    func updateTranslationConfig(baseURL: URL, token: String, translation: KGTranslationConfig) async throws -> KGUserConfig
}

private struct KGUserConfigPatch: Encodable {
    let integrations: KGUserIntegrationsConfig?
    let translation: KGTranslationConfig?
}

final class KGUserConfigClient: KGUserConfigRemoteHandling {
    func fetchUserConfig(baseURL: URL, token: String) async throws -> KGUserConfig {
        var request = URLRequest(url: baseURL.appendingPathComponent("api/user/config"))
        Self.applyAuth(to: &request, token: token)
        return try await perform(request)
    }

    func updateOptionalIntegrationKey(baseURL: URL, token: String, apiKey: String) async throws -> KGUserConfig {
        let patch = KGUserConfigPatch(
            integrations: KGUserIntegrationsConfig(
                mochi: KGOptionalIntegrationProviderConfig(api_key: apiKey)
            ),
            translation: nil
        )
        return try await update(baseURL: baseURL, token: token, patch: patch)
    }

    func updateTranslationConfig(baseURL: URL, token: String, translation: KGTranslationConfig) async throws -> KGUserConfig {
        let patch = KGUserConfigPatch(integrations: nil, translation: translation)
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
