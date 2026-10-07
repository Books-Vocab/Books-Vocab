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

    // MARK: - beforeSend exception redaction

    @Test func machCrashKeepsIdentityMechanismAndOnlyTheCodePrefix() {
        let redacted = SentryPrivacyPolicy.redactException(
            type: "EXC_BAD_ACCESS",
            value: "Exception 1, Code 1, Subcode 8 >\nAttempted to dereference garbage pointer 0x8.",
            mechanismType: "mach",
            handled: false
        )

        #expect(redacted == SentryPrivacyPolicy.RedactedException(
            type: "EXC_BAD_ACCESS",
            value: "Exception 1, Code 1, Subcode 8",
            mechanismType: "mach",
            handled: false
        ))
    }

    @Test func signalCrashKeepsSignalCodesAndUnhandledFlag() {
        let redacted = SentryPrivacyPolicy.redactException(
            type: "SIGABRT",
            value: "Signal 6, Code 0",
            mechanismType: "signal",
            handled: false
        )

        #expect(redacted.type == "SIGABRT")
        #expect(redacted.value == "Signal 6, Code 0")
        #expect(redacted.mechanismType == "signal")
        #expect(redacted.handled == false)
    }

    @Test func swiftRuntimeTrapKeepsOnlyTheStaticRuntimePhrase() {
        let redacted = SentryPrivacyPolicy.redactException(
            type: "EXC_BREAKPOINT",
            value: "BooksAndVocab/DeckView.swift:42: Fatal error: Unexpectedly found nil while unwrapping an Optional value",
            mechanismType: "mach",
            handled: false
        )
        let custom = SentryPrivacyPolicy.redactException(
            type: "EXC_BREAKPOINT",
            value: "Fatal error: could not load deck for person@example.com",
            mechanismType: "mach",
            handled: false
        )

        #expect(redacted.value == "Fatal error: Unexpectedly found nil while unwrapping an Optional value")
        #expect(custom.type == "EXC_BREAKPOINT")
        #expect(custom.value == nil)
    }

    @Test func nsexceptionCrashKeepsNameButNeverTheReason() {
        let redacted = SentryPrivacyPolicy.redactException(
            type: "NSInvalidArgumentException",
            value: "-[Deck title]: unrecognized selector for the user's book title",
            mechanismType: "nsexception",
            handled: false
        )

        #expect(redacted.type == "NSInvalidArgumentException")
        #expect(redacted.value == nil)
        #expect(redacted.mechanismType == "nsexception")
        #expect(redacted.handled == false)
    }

    @Test func appHangKeepsHangTypeAndStaticDurationText() {
        let fresh = SentryPrivacyPolicy.redactException(
            type: "App Hang Fully Blocked",
            value: "App hanging for at least 2000 ms.",
            mechanismType: "AppHang",
            handled: nil
        )
        let stopped = SentryPrivacyPolicy.redactException(
            type: "Fatal App Hang Non Fully Blocked",
            value: "App hanging between 2.0 and 3.5 seconds.",
            mechanismType: "AppHang",
            handled: nil
        )
        let legacy = SentryPrivacyPolicy.redactException(
            type: "App Hanging",
            value: "App hanging for at least 2000 ms.",
            mechanismType: "AppHang",
            handled: nil
        )

        #expect(fresh == SentryPrivacyPolicy.RedactedException(
            type: "App Hang Fully Blocked",
            value: "App hanging for at least 2000 ms.",
            mechanismType: "AppHang",
            handled: nil
        ))
        #expect(stopped.type == "Fatal App Hang Non Fully Blocked")
        #expect(stopped.value == "App hanging between 2.0 and 3.5 seconds.")
        #expect(legacy.type == "App Hanging")
    }

    @Test func unknownUnhandledMechanismKeepsFlagButUsesStrictTypeRules() {
        let redacted = SentryPrivacyPolicy.redactException(
            type: "Jane Doe wrote this",
            value: "free-form reason with user text",
            mechanismType: "user",
            handled: false
        )

        #expect(redacted == SentryPrivacyPolicy.RedactedException(
            type: "ReportedError",
            value: nil,
            mechanismType: "user",
            handled: false
        ))
    }

    @Test func handledCapturedErrorKeepsTodaysRedaction() {
        let redacted = SentryPrivacyPolicy.redactException(
            type: "BooksAndVocab.KGError",
            value: "httpError(statusCode: 500, detail: \"the user's book title\")",
            mechanismType: "NSError",
            handled: true
        )
        let opaque = SentryPrivacyPolicy.redactException(
            type: "the user's book title",
            value: "Code: 5",
            mechanismType: nil,
            handled: nil
        )

        #expect(redacted == SentryPrivacyPolicy.RedactedException(
            type: "BooksAndVocab.KGError",
            value: nil,
            mechanismType: nil,
            handled: nil
        ))
        #expect(opaque == SentryPrivacyPolicy.RedactedException(
            type: "ReportedError",
            value: nil,
            mechanismType: nil,
            handled: nil
        ))
    }

    @Test func crashTypesFollowMechanismSpecificRules() {
        func type(_ type: String?, _ mechanism: String) -> String {
            SentryPrivacyPolicy.redactException(
                type: type, value: nil, mechanismType: mechanism, handled: false
            ).type
        }

        #expect(type("EXC_BAD_ACCESS", "mach") == "EXC_BAD_ACCESS")
        #expect(type("Jane Doe", "mach") == "Mach Exception")
        #expect(type("SIGABRT", "signal") == "SIGABRT")
        #expect(type("SIGSEGV", "signal") == "SIGSEGV")
        #expect(type("reason: the user's book title", "signal") == "Signal Exception")
        #expect(type("NSInvalidArgumentException", "nsexception") == "NSInvalidArgumentException")
        #expect(type("BooksAndVocab.StoreError", "nsexception") == "BooksAndVocab.StoreError")
        #expect(type("Jane Doe", "nsexception") == "NSException")
        #expect(type("JaneDoe", "nsexception") == "NSException")
        #expect(type(nil, "nsexception") == "NSException")
        #expect(type("std::runtime_error", "cpp_exception") == "C++ Exception")
        #expect(type("App Hang Non Fully Blocked", "AppHang") == "App Hang Non Fully Blocked")
        #expect(type("App Hang by Jane Doe", "AppHang") == "App Hanging")
        #expect(type("WatchdogTermination", "watchdog_termination") == "WatchdogTermination")
        #expect(type("Jane Doe", "watchdog_termination") == "WatchdogTermination")
    }

    @Test func onlyAllowlistedStaticVerificationMessageSurvives() {
        #expect(SentryPrivacyPolicy.redactEventMessage(SentryPrivacyPolicy.verificationMessage)
            == "Sentry verification: iOS launch-arg test event")
        #expect(SentryPrivacyPolicy.redactEventMessage("Sentry verification: the user's book title") == nil)
        #expect(SentryPrivacyPolicy.redactEventMessage("sync failed for person@example.com") == nil)
        #expect(SentryPrivacyPolicy.redactEventMessage(nil) == nil)
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
