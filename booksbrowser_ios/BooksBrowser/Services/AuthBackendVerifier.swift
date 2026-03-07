import Foundation

struct AuthVerificationResult: Sendable {
    let userId: String
    let accessToken: String
}

protocol AuthVerifying: AnyObject {
    func verify(provider: String, token: String, email: String?) async throws -> AuthVerificationResult
}

final class AuthBackendVerifier: AuthVerifying {
    func verify(provider: String, token: String, email: String?) async throws -> AuthVerificationResult {
        let serverURL = KGService.getServerURL()

        guard let url = URL(string: "\(serverURL)/auth/verify") else {
            throw AuthVerificationError.invalidURL(serverURL)
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let payload: [String: Any] = [
            "provider": provider,
            "token": token,
            "email": email ?? NSNull()
        ]

        request.httpBody = try JSONSerialization.data(withJSONObject: payload)

        let (data, _) = try await URLSession.shared.data(for: request)
        guard !data.isEmpty else {
            throw AuthVerificationError.emptyResponse
        }

        guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw AuthVerificationError.invalidResponse
        }

        guard
            let accessToken = json["access_token"] as? String,
            let userId = json["user_id"] as? String
        else {
            throw AuthVerificationError.missingCredentials(keys: Array(json.keys))
        }

        return AuthVerificationResult(userId: userId, accessToken: accessToken)
    }
}

enum AuthVerificationError: LocalizedError {
    case invalidURL(String)
    case emptyResponse
    case invalidResponse
    case missingCredentials(keys: [String])

    var errorDescription: String? {
        switch self {
        case .invalidURL(let base):
            return "Invalid backend URL: \(base)/auth/verify"
        case .emptyResponse:
            return "Response body is empty"
        case .invalidResponse:
            return "Invalid JSON response format"
        case .missingCredentials(let keys):
            return "Missing access_token or user_id. Keys: \(keys.joined(separator: ", "))"
        }
    }
}
