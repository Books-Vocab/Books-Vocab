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

    @Test func decodesTypographicAndUppercaseEntities() {
        let words = ReadiumService.extractWords(fromHTML: "<p>&ldquo;Hello&rdquo; &Eacute;cole &Uuml;ber</p>")
        #expect(words.contains("hello"))
        #expect(words.contains("\u{E9}cole"))
        #expect(words.contains("\u{FC}ber"))
        #expect(!words.contains("ldquo"))
        #expect(!words.contains("rdquo"))
        #expect(!words.contains("eacute"))
    }

    @Test func insertsFragmentsAlongsideWholeToken() {
        let words = ReadiumService.extractWords(fromHTML: "<p>well-known king's covid-19 mp3 \u{FB01}sh</p>")
        #expect(words.contains("well-known"))
        #expect(words.contains("well"))
        #expect(words.contains("known"))
        #expect(words.contains("king's"))
        #expect(words.contains("king"))
        #expect(words.contains("covid-19"))
        #expect(words.contains("covid"))
        #expect(words.contains("mp3"))
        #expect(words.contains("fish"))
        #expect(!words.contains("s"))
    }

    @Test func dropsSingleLettersAndTrimsEdgePunctuation() {
        let words = ReadiumService.extractWords(fromHTML: "<p>a I -dash- 'quoted' end--</p>")
        #expect(words == ["dash", "quoted", "end"])
    }
}
