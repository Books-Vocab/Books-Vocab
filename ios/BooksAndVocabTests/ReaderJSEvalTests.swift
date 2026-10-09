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
import JavaScriptCore
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

    // MARK: - Context sentence for a repeated word (#2531)

    private func evaluateContext(fullText: String, word: String, tapOffset: Int?) -> String? {
        let context = JSContext()!
        context.evaluateScript("""
        var window = {}; var navigator = { language: 'en' };
        var document = { addEventListener: function(){}, documentElement: { lang: 'en' } };
        var el = { tagName: 'P', textContent: \(Self.jsLiteral(fullText)), parentElement: null };
        """)
        context.evaluateScript(ReadiumNavigatorJS.buildSelectionScript(isDebugMode: "false"))
        let offset = tapOffset.map(String.init) ?? "undefined"
        let value = context.evaluateScript("extractContextFromElement(el, \(Self.jsLiteral(word)), \(offset))")
        return context.exception == nil ? value?.toString() : nil
    }

    private static func jsLiteral(_ text: String) -> String {
        let data = try! JSONSerialization.data(withJSONObject: [text])
        let array = String(decoding: data, as: UTF8.self)
        return String(array.dropFirst().dropLast())
    }

    private static let repeatedWordText = "The bank of the river was steep. He sat on the bank and fished all day. Later the bank closed for the evening. We walked home slowly after that."

    /// A word that appears in several sentences must take its context from the
    /// sentence that was tapped, not from the first sentence containing it.
    @Test func contextFollowsTappedOccurrenceOfRepeatedWord() throws {
        let text = Self.repeatedWordText
        let secondBank = try #require(text.range(of: "bank and"))
        let offset = text.distance(from: text.startIndex, to: secondBank.lowerBound)
        let result = try #require(evaluateContext(fullText: text, word: "bank", tapOffset: offset))
        #expect(result.contains("He sat on the bank and fished"))
        #expect(result.contains("Later the bank closed"))
    }

    @Test func contextTapInLastSentenceOccurrenceUsesThatSentence() throws {
        let text = "Cats sleep. Dogs run. Cats eat fish. Birds fly. Cats purr loudly."
        let lastCats = try #require(text.range(of: "Cats purr"))
        let offset = text.distance(from: text.startIndex, to: lastCats.lowerBound)
        let result = try #require(evaluateContext(fullText: text, word: "Cats", tapOffset: offset))
        #expect(result.contains("Cats purr loudly."))
        #expect(!result.contains("Cats sleep."))
    }

    @Test func contextWithoutTapOffsetKeepsFirstOccurrenceBehavior() throws {
        let result = try #require(evaluateContext(fullText: Self.repeatedWordText, word: "bank", tapOffset: nil))
        #expect(result.contains("The bank of the river was steep."))
    }

    // MARK: - Vocab bridge script encoding (#2443)

    private static let hostileWords = ["alpha", "line1\nline2\r", "a\u{2028}b\u{2029}c", "q\"uote\\"]

    private func makeContext() -> JSContext {
        let context = JSContext()!
        context.evaluateScript("var window = {}; window.__markVocabWords = function(w){ window.got = w };"
            + " window.__markVocabWord = function(w){ window.got = w };")
        return context
    }

    /// Control chars / U+2028/2029 in one word must neither break the script
    /// nor drop the other words of the batch.
    @Test func markVocabWordsScriptSurvivesLineTerminators() {
        let context = makeContext()
        context.evaluateScript(ReaderJSEval.markVocabWordsScript(Self.hostileWords))
        #expect(context.exception == nil)
        let got = context.evaluateScript("window.got")?.toArray() as? [String]
        #expect(got == Self.hostileWords)
    }

    @Test func singleWordScriptRoundTripsHostileWords() {
        for word in Self.hostileWords {
            let context = makeContext()
            context.evaluateScript(ReaderJSEval.singleWordScript(function: "__markVocabWord", word: word))
            #expect(context.exception == nil)
            #expect(context.evaluateScript("window.got")?.toString() == word)
        }
    }
}
#endif
