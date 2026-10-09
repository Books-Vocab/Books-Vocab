//
//  ReadiumBookWordExtractionTests.swift
//  Books & Vocab Tests
//

import Testing
@testable import BooksAndVocab

@MainActor
struct ReadiumBookWordExtractionTests {

    @Test func keepsHyphenatedApostropheAndAccentedWords() {
        let html = "<p class=\"x\">A well-known caf\u{00E9}; don't stop, <b>Don\u{2019}t</b> go.</p>"
        let words = ReadiumService.extractWords(fromHTML: html)
        #expect(words.contains("well-known"))
        #expect(words.contains("don't"))
        #expect(words.contains("caf\u{00E9}"))
        #expect(!words.contains("class"))
        #expect(filterValidWords(["well-known", "don't", "caf\u{00E9}"], bookWords: words).count == 3)
    }

    @Test func decodesEntitiesBeforeTokenizing() {
        let html = "<p>caf&eacute; don&#39;t don&rsquo;t it&apos;s &amp;amp; fish&nbsp;chips</p>"
        let words = ReadiumService.extractWords(fromHTML: html)
        #expect(words.contains("caf\u{00E9}"))
        #expect(words.contains("don't"))
        #expect(words.contains("it's"))
        #expect(words.contains("fish"))
        #expect(words.contains("chips"))
        #expect(!words.contains("eacute"))
        #expect(!words.contains("rsquo"))
        #expect(!words.contains("nbsp"))
    }

    @Test func dropsSingleLettersAndTrimsEdgePunctuation() {
        let words = ReadiumService.extractWords(fromHTML: "<p>a I -dash- 'quoted' end--</p>")
        #expect(words == ["dash", "quoted", "end"])
    }
}
