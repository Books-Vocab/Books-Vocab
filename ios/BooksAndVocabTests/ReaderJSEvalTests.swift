//
//  ReaderJSEvalTests.swift
//  Books & Vocab Tests
//
//  Spec for Phase 0 (reader observability): JS eval result classification.
//
//  Root cause: every `navigator.evaluateJavaScript` call site in
//  ReadiumNavigatorCoordinator+Highlighting / ReaderDOMExecutor discarded its
//  `Result<Any, Error>` (`_ = await …`), so failed highlight/DOM injections
//  produced no signal. The fix routes results through `ReaderJSEval`, demoting
//  the EXPECTED `.spreadNotLoaded` race to debug while surfacing real failures.
//
//  NOTE: This target cannot run locally in this environment (CLAUDE.md Scope
//  forbids ios_test.sh here). These cases are the executable spec for the
//  classification seam, validated by CI / reviewer.
//

#if os(iOS)
import Foundation
import Testing
import ReadiumNavigator
@testable import BooksAndVocab

@MainActor
struct ReaderJSEvalTests {

    /// A successful eval is a no-op outcome (no log noise).
    @Test func successClassifiesAsOk() {
        #expect(ReaderJSEval.classify(.success("done")) == .ok)
    }

    /// The pre-resource-load race must NOT be treated as a failure, else initial
    /// load and every page-turn would flood the error log.
    @Test func spreadNotLoadedIsExpectedRaceNotFailure() {
        let result: Result<Any, Error> = .failure(EPUBNavigatorViewController.EPUBError.spreadNotLoaded)
        #expect(ReaderJSEval.classify(result) == .spreadNotLoaded)
    }

    /// Any other error is a genuine anomaly that must surface.
    @Test func otherErrorClassifiesAsFailed() {
        let result: Result<Any, Error> = .failure(NSError(domain: "JS", code: 42))
        guard case .failed = ReaderJSEval.classify(result) else {
            Issue.record("expected .failed for a non-spreadNotLoaded error")
            return
        }
    }

    /// EPUB content is not limited to ASCII words: the converter already
    /// preserves Latin-1 text such as `café`. The selection scanner must use
    /// Unicode letter boundaries or a tap on that word is truncated to `caf`.
    @Test func selectionScriptTreatsUnicodeLettersAsWordCharacters() {
        let script = ReadiumNavigatorJS.buildSelectionScript(isDebugMode: "false")

        #expect(script.contains("\\p{L}"))
        #expect(script.contains("\\p{M}"))
        #expect(script.contains("\\p{N}"))
        #expect(script.contains("]/u"),
                "the Unicode character class must be emitted as a JavaScript regex with the u flag")
        #expect(!script.contains("[a-zA-Z'\\\\-]"),
                "selection must not truncate non-ASCII Latin words")
    }
}
#endif
