import Foundation
import Testing
@testable import BooksAndVocab

/// 非 2xx 必須以 `httpStatus` 浮現，不可被當成成功 payload 解析成誤導性的 missingCredentials / NSError。
@Suite(.serialized)
struct AuthBackendVerifierStatusTests {
    @Test(arguments: [
        (401, #"{"detail":"bad token"}"#),
        (502, "<html>Bad Gateway</html>"),
        (503, "")
    ])
    func non2xx_throws_httpStatus(code: Int, body: String) async {
        AuthVerifyStubProtocol.set(status: code, body: Data(body.utf8))
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [AuthVerifyStubProtocol.self]
        let verifier = AuthBackendVerifier(session: URLSession(configuration: configuration))
        do {
            _ = try await verifier.verify(provider: "google", token: "t", email: nil)
            Issue.record("expected httpStatus(\(code))")
        } catch let AuthVerificationError.httpStatus(got) {
            #expect(got == code)
        } catch {
            Issue.record("unexpected error \(error)")
        }
    }
}

/// 只掛在 local ephemeral session 上，不 registerClass；suite 為 serialized，單一 static 回應即可。
private final class AuthVerifyStubProtocol: URLProtocol, @unchecked Sendable {
    private static let lock = NSLock()
    nonisolated(unsafe) private static var status = 200
    nonisolated(unsafe) private static var body = Data()

    static func set(status: Int, body: Data) {
        lock.withLock {
            Self.status = status
            Self.body = body
        }
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let (status, body) = Self.lock.withLock { (Self.status, Self.body) }
        guard let url = request.url,
              let response = HTTPURLResponse(url: url, statusCode: status, httpVersion: nil, headerFields: nil)
        else {
            client?.urlProtocol(self, didFailWithError: URLError(.badURL))
            return
        }
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        if !body.isEmpty { client?.urlProtocol(self, didLoad: body) }
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}
