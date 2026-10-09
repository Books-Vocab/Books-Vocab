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

    /// #2531 acceptance: an earlier sentence holds the tapped word only as a
    /// substring ("he" inside "The"/"other"/"there"); the tap must resolve to
    /// the real whole-word occurrence in the later sentence.
    @Test func contextIgnoresEarlierSentenceWhereWordIsOnlyASubstring() throws {
        let text = "The other brother left there. Nothing more was said. Rain fell hard. Then he ran home. Everyone slept."
        let tapped = try #require(text.range(of: "he ran"))
        let offset = text.distance(from: text.startIndex, to: tapped.lowerBound)
        let result = try #require(evaluateContext(fullText: text, word: "he", tapOffset: offset))
        #expect(result.contains("Then he ran home."))
        #expect(!result.contains("The other brother left there."))
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

    // MARK: - Vocab marking DOM behaviour (#2739, #2740) — JavaScriptCore + minimal fake DOM

    private static let fakeDOM = """
    var NodeFilter = { SHOW_TEXT: 4 };
    class N {
        constructor(type, tag, text) { this.nodeType = type; this.tagName = tag; this._text = text || ''; this.children = []; this.parentNode = null; this.attrs = {}; this.className = ''; }
        get parentElement() { return this.parentNode && this.parentNode.nodeType === 1 ? this.parentNode : null; }
        get childNodes() { return this.children; }
        get classList() { var s = this; return { contains: function(c) { return (' ' + s.className + ' ').indexOf(' ' + c + ' ') >= 0; }, remove: function() { var rm = Array.prototype.slice.call(arguments); s.className = s.className.split(' ').filter(function(x) { return x && rm.indexOf(x) < 0; }).join(' '); } }; }
        get firstChild() { return this.children[0] || null; }
        insertBefore(n, ref) { if (n.parentNode) { n.parentNode.removeChild(n); } n.parentNode = this; this.children.splice(this.children.indexOf(ref), 0, n); }
        removeChild(n) { this.children.splice(this.children.indexOf(n), 1); n.parentNode = null; }
        normalize() { var out = []; this.children.forEach(function(c) { var l = out[out.length - 1]; if (c.nodeType === 3 && l && l.nodeType === 3) { l._text += c._text; } else { out.push(c); } }); this.children = out; }
        get textContent() { return this.nodeType === 3 ? this._text : this.children.map(function(c) { return c.textContent; }).join(''); }
        set textContent(v) { if (this.nodeType === 3) { this._text = v; } else { var t = new N(3, '', v); t.parentNode = this; this.children = [t]; } }
        setAttribute(k, v) { this.attrs[k] = v; }
        getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
        removeAttribute(k) { delete this.attrs[k]; }
        appendChild(c) { var self = this; (c.nodeType === 11 ? c.children.splice(0) : [c]).forEach(function(x) { if (x.parentNode) { x.parentNode.removeChild(x); } x.parentNode = self; self.children.push(x); }); return c; }
        replaceChild(n, old) { var self = this; var items = n.nodeType === 11 ? n.children.splice(0) : [n]; items.forEach(function(x) { x.parentNode = self; }); var i = this.children.indexOf(old); this.children.splice.apply(this.children, [i, 1].concat(items)); old.parentNode = null; }
    }
    function el(tag, kids) { var e = new N(1, tag); kids.forEach(function(k) { e.appendChild(typeof k === 'string' ? new N(3, '', k) : k); }); return e; }
    function all(root, out) { root.children.forEach(function(c) { out.push(c); all(c, out); }); return out; }
    var body = el('BODY', []);
    var document = {
        body: body,
        createTreeWalker: function(root) { var l = all(root, []).filter(function(n) { return n.nodeType === 3; }); var i = -1; var w = { nextNode: function() { i++; w.currentNode = l[i]; return i < l.length; } }; return w; },
        createDocumentFragment: function() { return new N(11, ''); },
        createElement: function(t) { return new N(1, t.toUpperCase()); },
        createTextNode: function(t) { return new N(3, '', t); },
        querySelectorAll: function() { return all(body, []).filter(function(n) { return n.nodeType === 1 && n.className.indexOf('vocab-word') >= 0; }); },
        querySelector: function(q) { return document.querySelectorAll(q)[0] || null; }
    };
    var window = { webkit: { messageHandlers: { markingProgress: { postMessage: function() {} } } } };
    var setTimeout = function(f) { f(); };
    function dump(n) { if (n.nodeType === 3) return '"' + n._text + '"'; var inner = n.children.map(dump).join(','); if (n.className.indexOf('vocab-word') >= 0) return '<w:' + n.attrs['data-word'] + '>' + inner + '</w>'; return n.tagName + '[' + inner + ']'; }
    """

    private func runVocabScript(_ call: String, body bodyJS: String) -> String {
        let context = JSContext()!
        context.evaluateScript(Self.fakeDOM)
        context.evaluateScript(ReadiumNavigatorJS.buildHighlightScript())
        context.evaluateScript("body.appendChild(\(bodyJS));")
        context.evaluateScript(call)
        #expect(context.exception == nil, "\(context.exception?.toString() ?? "")")
        return context.evaluateScript("dump(body)")?.toString() ?? "<no result>"
    }

    /// `\b` is ASCII-only in JS (even with the u flag), so `café.` never matched (#2740).
    @Test func markVocabWordMatchesAccentedWordBeforePunctuation() {
        let dump = runVocabScript("window.__markVocabWord('café')", body: "el('P', ['Un café.'])")
        #expect(dump == #"BODY[P["Un ",<w:café>"café"</w>,"."]]"#)
    }

    @Test func markVocabWordsMatchesAccentedWordsAndKeepsLetterBoundaries() {
        let dump = runVocabScript("window.__markVocabWords(['élan', 'café'])",
                                  body: "el('P', ['un élan, cafés, café'])")
        #expect(dump == #"BODY[P["un ",<w:élan>"élan"</w>,", cafés, ",<w:café>"café"</w>]]"#)
    }

    /// Cross-node fallback wraps each overlapping segment in place and keeps the
    /// inline parent (`<i>`) intact; the word is tagged via data-word (#2739).
    @Test func crossNodeHyphenatedWordIsWrappedPerSegment() {
        let dump = runVocabScript("window.__markVocabWord('well-known')",
                                  body: "el('P', ['a ', el('I', ['well-']), 'known fact'])")
        #expect(dump == #"BODY[P["a ",I[<w:well-known>"well-"</w>],<w:well-known>"known"</w>," fact"]]"#)
    }

    /// No match across unrelated nodes / inside a longer word / across blocks.
    @Test func crossNodeFallbackDoesNotWrapUnrelatedText() {
        let longer = runVocabScript("window.__markVocabWord('well-known')",
                                    body: "el('P', ['unwell-', el('I', ['known']), ' x'])")
        #expect(!longer.contains("<w:"))
        let blocks = runVocabScript("window.__markVocabWord('well-known')",
                                    body: "el('DIV', [el('P', ['well-']), el('P', ['known'])])")
        #expect(!blocks.contains("<w:"))
    }

    /// Removal and the tap payload both key off data-word, so every segment of a
    /// split word is removed together.
    @Test func removeVocabWordUnwrapsEverySegmentByDataWord() {
        let dump = runVocabScript("window.__markVocabWord('well-known'); window.__removeVocabWord('well-known')",
                                  body: "el('P', ['a ', el('I', ['well-']), 'known fact'])")
        #expect(dump == #"BODY[P["a ",I["well-"],"known fact"]]"#)
    }
}
#endif
