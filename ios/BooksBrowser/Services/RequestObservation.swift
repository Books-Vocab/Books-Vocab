import Foundation

enum RequestObservation {
    static let headerName = "X-Request-ID"

    static func attachRequestID(to request: inout URLRequest) -> String {
        if let existing = request.value(forHTTPHeaderField: headerName), !existing.isEmpty {
            return existing
        }

        let requestID = String(UUID().uuidString.replacingOccurrences(of: "-", with: "").prefix(16))
        request.setValue(requestID, forHTTPHeaderField: headerName)
        return requestID
    }

    static func responseRequestID(from response: HTTPURLResponse, fallback requestID: String) -> String {
        if let responseRequestID = response.value(forHTTPHeaderField: headerName),
           !responseRequestID.isEmpty {
            return responseRequestID
        }
        return requestID
    }
}
