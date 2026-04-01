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
        guard NetworkMonitor.shared.isConnected else {
            throw AuthVerificationError.offline
        }

        let serverURL = KGService.getServerURL()

        guard let url = URL(string: "\(serverURL)/auth/verify") else {
            throw AuthVerificationError.invalidURL(serverURL)
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let requestID = RequestObservation.attachRequestID(to: &request)

        let payload: [String: Any] = [
            "provider": provider,
            "token": token,
            "email": email ?? NSNull()
        ]

        request.httpBody = try JSONSerialization.data(withJSONObject: payload)

        let (data, response) = try await sharedURLSession.data(for: request)
        if let httpResponse = response as? HTTPURLResponse, !(200...299).contains(httpResponse.statusCode) {
            let responseRequestID = RequestObservation.responseRequestID(from: httpResponse, fallback: requestID)
            AppLog.auth.error("Auth verify failed [\(httpResponse.statusCode)] request_id=\(responseRequestID)")
        }
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
    case offline

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
        case .offline:
            return L10n.string("目前沒有網路連線，無法登入")
        }
    }
}
