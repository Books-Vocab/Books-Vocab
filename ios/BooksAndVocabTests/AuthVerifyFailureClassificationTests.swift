import Foundation
import Testing
@testable import BooksAndVocab

struct AuthVerifyFailureClassificationTests {
    @Test func offlineCausesClassifyAsOffline() {
        #expect(AuthManager.classifyVerifyFailure(AuthVerificationError.offline) == .offline)
        #expect(AuthManager.classifyVerifyFailure(KGError.offline) == .offline)
        #expect(AuthManager.classifyVerifyFailure(URLError(.notConnectedToInternet)) == .offline)
    }

    @Test func cancellationIsSilent() {
        #expect(AuthManager.classifyVerifyFailure(CancellationError()) == .cancelled)
        #expect(AuthManager.classifyVerifyFailure(URLError(.cancelled)) == .cancelled)
    }

    @Test func otherErrorsFallBackToServer() {
        #expect(AuthManager.classifyVerifyFailure(AuthVerificationError.httpStatus(500)) == .server)
        #expect(AuthManager.classifyVerifyFailure(URLError(.badServerResponse)) == .server)
    }
}
