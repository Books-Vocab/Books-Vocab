//
//  VocabularyExporterPOSTests.swift
//  Books & Vocab Tests
//
//  Guards that partOfSpeech is actually emitted in every export format.
//  Regression: CSV header advertised "Part of Speech" but the value was
//  hard-coded empty; JSON/Anki dropped POS entirely.
//

import Foundation
import Testing
@testable import BooksBrowser

@Suite(.serialized)
struct VocabularyExporterPOSTests {

    private func makeEntry() -> VocabularyEntry {
        VocabularyEntry(
            word: "invoke",
            translation: "引用",
            context: "The lawyer invoked the law.",
            explanation: "to call upon",
            partOfSpeech: "v.",
            bookTitle: "Law 101"
        )
    }

    private func read(_ url: URL?) throws -> String {
        let url = try #require(url)
        defer { try? FileManager.default.removeItem(at: url) }
        return try String(contentsOf: url, encoding: .utf8)
    }

    @Test func test_csv_emits_part_of_speech() throws {
        let csv = try read(VocabularyExporter.exportAsCSV(entries: [makeEntry()]))
        // Third column (Part of Speech) must carry the value, not "".
        #expect(csv.contains("\"v.\""))
    }

    @Test func test_json_emits_part_of_speech() throws {
        let json = try read(VocabularyExporter.exportAsJSON(entries: [makeEntry()]))
        #expect(json.contains("partOfSpeech"))
        #expect(json.contains("v."))
    }

    @Test func test_anki_emits_part_of_speech() throws {
        let tsv = try read(VocabularyExporter.exportAsAnki(entries: [makeEntry()]))
        #expect(tsv.contains("v."))
    }

    @Test func test_csv_nil_pos_stays_empty() throws {
        let entry = VocabularyEntry(
            word: "the",
            translation: "這",
            context: "the cat",
            bookTitle: "B"
        )
        let csv = try read(VocabularyExporter.exportAsCSV(entries: [entry]))
        // Header + one row. Row column 3 is empty quotes.
        let rows = csv.split(separator: "\n")
        #expect(rows.count == 2)
        #expect(rows[1].contains("\"the\",\"這\",\"\","))
    }

    @Test func test_csv_pos_with_comma_is_escaped() throws {
        let entry = VocabularyEntry(
            word: "set",
            translation: "放",
            context: "set it down",
            partOfSpeech: "v., n.",
            bookTitle: "B"
        )
        let csv = try read(VocabularyExporter.exportAsCSV(entries: [entry]))
        #expect(csv.contains("\"v., n.\""))
    }
}
