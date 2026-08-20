import Testing
@testable import BooksAndVocab

struct SentryPrivacyPolicyTests {
    @Test func queryStringsAreRemovedBeforeDiagnosticsLeaveTheApp() {
        #expect(SentryPrivacyPolicy.stripQuery(from: "/api/books?token=secret") == "/api/books")
        #expect(SentryPrivacyPolicy.stripQuery(from: "/api/books") == "/api/books")
        #expect(SentryPrivacyPolicy.redactBreadcrumbMessage("GET /api/books?code=secret") == "GET /api/books")
        #expect(SentryPrivacyPolicy.redactBreadcrumbURL("/api/vocab/user-supplied-book?token=secret") == "/api/vocab")
        #expect(SentryPrivacyPolicy.redactBreadcrumbURL("https://user:password@example.test/api/vocab/book") == nil)
        #expect(SentryPrivacyPolicy.redactBreadcrumbURL("/api/private-user-input") == nil)
        #expect(SentryPrivacyPolicy.redactBreadcrumbMessage("the user's book title") == nil)
    }

    @Test func userAndRequestIDsOnlyAcceptOpaqueValues() {
        #expect(SentryPrivacyPolicy.redactUserID("internal-user-123") == "internal-user-123")
        #expect(SentryPrivacyPolicy.redactUserID("person@example.com") == nil)
        #expect(SentryPrivacyPolicy.redactUserID("bearer token") == nil)
        #expect(SentryPrivacyPolicy.redactRequestID("req-123") == "req-123")
        #expect(SentryPrivacyPolicy.redactRequestID("request id with spaces") == nil)
    }

    @Test func breadcrumbDataUsesAllowlistAndStripsSensitiveValues() {
        let redacted = SentryPrivacyPolicy.redactBreadcrumbData([
            "request_id": "req-123",
            "url": "/api/decks?cursor=secret",
            "source": "series_abc/ep_03",
            "status_code": 500,
            "method": "GET",
            "search_text": "the user's book title",
            "Authorization": "Bearer secret"
        ])

        #expect(redacted?["request_id"] as? String == "req-123")
        #expect(redacted?["url"] as? String == "/api/decks")
        #expect(redacted?["source"] as? String == "series_abc/ep_03")
        #expect(redacted?["status_code"] as? Int == 500)
        #expect(redacted?["method"] as? String == "GET")
        #expect(redacted?["search_text"] == nil)
        #expect(redacted?["authorization"] == nil)
    }

    @Test func cancellationAndSensitiveFieldRulesAreExplicit() {
        #expect(SentryPrivacyPolicy.isCancellationExceptionType("CancellationError"))
        #expect(SentryPrivacyPolicy.isCancellationExceptionType("NSURLErrorCancelled"))
        #expect(SentryPrivacyPolicy.isCancellationException(type: "Swift.CancellationError", value: nil))
        #expect(SentryPrivacyPolicy.isCancellationException(type: "NSError", value: "NSURLErrorDomain error -999"))
        #expect(!SentryPrivacyPolicy.isCancellationExceptionType("KGError"))
        #expect(SentryPrivacyPolicy.redactExceptionType("NetworkError") == "NetworkError")
        #expect(SentryPrivacyPolicy.redactExceptionType("user_book_title") == nil)
        #expect(SentryPrivacyPolicy.redactExceptionType("Error with user text") == nil)
        #expect(SentryPrivacyPolicy.isSensitiveField("Authorization"))
        #expect(SentryPrivacyPolicy.isSensitiveField("request_body"))
        #expect(!SentryPrivacyPolicy.isSensitiveField("status_code"))
    }

    @Test func diagnosticContextIsBoundedAndKeepsOnlyRedactedCorrelation() {
        let context = AppDiagnosticContext(maxObservations: 2, maxRequestIDs: 2)
        context.recordObservation(message: "sync.start", requestID: "req-1")
        context.recordObservation(message: "GET /api/decks?token=secret", requestID: "req-2")
        context.recordObservation(message: "sync.end", requestID: "req-3")
        context.recordEventID("0123456789abcdef0123456789abcdef")

        let snapshot = context.snapshot()
        #expect(snapshot.observations == ["GET /api/decks", "sync.end"])
        #expect(snapshot.requestIDs == ["req-2", "req-3"])
        #expect(snapshot.latestSentryEventID == "0123456789abcdef0123456789abcdef")
    }
}
